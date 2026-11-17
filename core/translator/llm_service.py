import json
import os
import re
import logging
import time
from threading import RLock
from typing import Dict, List
import requests
from dotenv import load_dotenv
from core.cache import BoundedCache

load_dotenv()
log = logging.getLogger(__name__)

class MangaLLMTranslator:
    SYSTEM_PROMPT = (
        "Ты — профессиональный переводчик японской манги на русский язык.\n"
        "ПРАВИЛА:\n"
        "1. Переводи КАЖДУЮ реплику на русский язык живо, естественно и кратко.\n"
        "2. КАТЕГОРИЧЕСКИ ЗАПРЕЩЕНО оставлять японские иероглифы или кану в ответе!\n"
        "3. Фразы без местоимений в диалоге ('そこにいたんだ！', '大丈夫？') переводи во 2-м лице ('О, так ты здесь!', 'Ты в порядке?').\n"
        "4. Отвечай СТРОГО валидным JSON: {\"bubbles\": [\"перевод\"]}"
    )

    def __init__(self, model: str | None = None, url: str | None = None):
        self.url = url or os.getenv("OLLAMA_URL", "http://localhost:11434/api/chat")
        self.model = model or os.getenv("OLLAMA_MODEL", "gemma2:9b")
        self.glossary: Dict[str, str] = {}
        self.session = requests.Session()
        adapter = requests.adapters.HTTPAdapter(pool_connections=1, pool_maxsize=1, max_retries=0)
        self.session.mount('http://', adapter)
        self.session.mount('https://', adapter)
        self._request_lock = RLock()
        self._cache = BoundedCache(1024)
        self._compact_cache = BoundedCache(256)
        self.batch_size = 4
        # Keep one runner configuration across single/group/compaction calls;
        # changing num_ctx between stages can force an expensive runner reload.
        self.context_size = 1024
        self._disabled_group_contexts = set()

    def _chat(self, payload, read_timeout=45):
        start = time.perf_counter()
        with self._request_lock:
            response = self.session.post(self.url, json=payload, timeout=(5, read_timeout))
            response.raise_for_status()
            result = response.json()
        if not isinstance(result, dict):
            raise ValueError('Ollama response must be a JSON object')
        log.info('Ollama: %.2fs, prompt tokens=%s, output tokens=%s',
                 time.perf_counter() - start, result.get('prompt_eval_count', '?'), result.get('eval_count', '?'))
        return result

    def _cache_context(self):
        return self.url, self.model, self.SYSTEM_PROMPT, tuple(sorted(self.glossary.items()))

    @staticmethod
    def _valid_translation(value):
        return isinstance(value, str) and bool(value.strip()) and not re.search(r'[\u3040-\u30ff\u4e00-\u9fff]', value)

    def set_glossary(self, new_glossary: Dict[str, str]):
        self.glossary.update(new_glossary)
        self._cache.clear()
        self._compact_cache.clear()

    def compact_bubble_translation(self, source, translation, max_chars, max_word_chars):
        """Batch-only overflow retry. Existing screen translation is unchanged."""
        key = self._cache_context(), source, translation, max_chars, max_word_chars
        cached = self._compact_cache.get(key)
        if cached is not None:
            return cached
        payload = {
            'model': self.model, 'format': 'json', 'stream': False, 'keep_alive': '30m',
            'messages': [
                {'role': 'system', 'content': (
                    'Ты редактор русского перевода манги. Переформулируй реплику короче, '
                    'сохраняя смысл, вопрос, эмоцию и обращение. Используй короткие целые слова. '
                    'Не обрезай слова, не используй сокращения, не добавляй факты. '
                    'Ответ строго JSON: {"bubbles": ["короткая реплика"]}.')},
                {'role': 'user', 'content': json.dumps({
                    'original_japanese': source, 'russian_translation': translation,
                    'maximum_total_characters': max_chars,
                    'maximum_characters_per_word': max_word_chars}, ensure_ascii=False)}],
            'options': {'temperature': .1, 'num_predict': 128, 'num_ctx': self.context_size}}
        try:
            texts = json.loads(self._chat(payload)['message']['content']).get('bubbles', [])
            if len(texts) == 1 and self._valid_translation(texts[0]):
                result = texts[0].strip()
                self._compact_cache.put(key, result)
                return result
        except Exception as exc:
            print(f'[Ollama compact translation]: {exc}')
        return None

    def _translate_single(self, text: str) -> str:
        """Legacy single-line prompt, also used to recover malformed group replies."""
        messages = [
            {"role": "system", "content": self.SYSTEM_PROMPT},
            {
                "role": "user",
                "content": 'Переведи реплику из манги с японского на русский:\n["ご主人様体調悪そう…大丈夫？"]'
            },
            {
                "role": "assistant",
                "content": '{"bubbles": ["Господин, вы плохо выглядите... Всё в порядке?"]}'
            },
            {
                "role": "user",
                "content": f"Переведи реплику из манги с японского на русский:\n{json.dumps([text], ensure_ascii=False)}"
            }
        ]

        payload = {
            "model": self.model,
            "messages": messages,
            "format": "json",
            "keep_alive": "30m",
            "stream": False,
            "options": {
                "temperature": 0.1,
                "num_predict": 128,
                "num_ctx": self.context_size
            }
        }

        try:
            raw_content = self._chat(payload)["message"]["content"].strip()
            parsed = json.loads(raw_content)
            bubbles = parsed.get("bubbles", [])
            if bubbles and isinstance(bubbles, list):
                return str(bubbles[0])
            return text
        except Exception as e:
            print(f"[Ollama Error]: {e}")
            return text

    def _translate_group(self, texts):
        payload = {
            'model': self.model, 'stream': False, 'format': 'json', 'keep_alive': '30m',
            'messages': [
                {'role': 'system', 'content': self.SYSTEM_PROMPT + (
                    '\nДля списка объектов переведи каждый объект отдельно. Сохрани id, порядок и '
                    'все реплики и обращения; не объединяй и не сокращай их. Формат ответа для этого запроса: '
                    '{"bubbles":[{"id":0,"text":"перевод"}]}.')},
                {'role': 'user', 'content': '[{"id":0,"text":"ご主人様体調悪そう…大丈夫？"}]'},
                {'role': 'assistant', 'content': '{"bubbles":[{"id":0,"text":"Господин, вы плохо выглядите... Всё в порядке?"}]}'},
                {'role': 'user', 'content': json.dumps(
                    [{'id': i, 'text': text} for i, text in enumerate(texts)], ensure_ascii=False)}],
            'options': {'temperature': .1, 'num_predict': 128 * len(texts), 'num_ctx': self.context_size}}
        parsed = json.loads(self._chat(payload, read_timeout=45 * len(texts))['message']['content'])
        entries = parsed.get('bubbles')
        if not isinstance(entries, list) or len(entries) != len(texts):
            raise ValueError('Wrong translation count')
        mapped = {}
        for entry in entries:
            if not isinstance(entry, dict):
                raise ValueError('Missing translation id')
            index, value = entry.get('id'), entry.get('text')
            if type(index) is not int or not 0 <= index < len(texts) or index in mapped or not self._valid_translation(value):
                raise ValueError('Invalid translation id/text')
            mapped[index] = value.strip()
        return [mapped[i] for i in range(len(texts))]

    def translate_bubbles_batch(self, texts: List[str], target_lang: str = 'RU') -> List[str]:
        if not texts:
            return []
        context = self._cache_context(), target_lang
        resolved, missing = {}, []
        for text in texts:
            if text in resolved:
                continue
            if not text.strip():
                resolved[text] = ''
                continue
            cached = self._cache.get((context, text))
            if cached is not None:
                resolved[text] = cached
            else:
                resolved[text] = None
                missing.append(text)
        cursor = 0
        requests_count = 0
        while cursor < len(missing):
            group, chars = [], 0
            group_size = 1 if (self.url, self.model) in self._disabled_group_contexts else max(1, min(4, self.batch_size))
            while cursor < len(missing) and len(group) < group_size:
                text = missing[cursor]
                # Bound the prompt as well as the number of lines for 6GB VRAM.
                if group and chars + len(text) > 200:
                    break
                group.append(text)
                chars += len(text)
                cursor += 1
            requests_count += 1
            if len(group) == 1:
                values = [self._translate_single(group[0])]
            else:
                try:
                    values = self._translate_group(group)
                except requests.HTTPError as exc:
                    # The server may reject a larger generation (e.g. memory
                    # pressure). Fall back to the small request path once.
                    log.warning('Ollama отклонила группу (%s); повтор по одной реплике', exc)
                    self._disabled_group_contexts.add((self.url, self.model))
                    values = [self._translate_single(text) for text in group]
                    requests_count += len(group)
                except requests.RequestException as exc:
                    # A dead server must not cause four more timeout waits.
                    log.error('Ollama unavailable: %s', exc)
                    values = list(group)
                except (ValueError, TypeError, KeyError) as exc:
                    log.warning('Некорректный групповой ответ (%s); повтор по одной реплике', exc)
                    # If this installation/model ignores the grouped format,
                    # do not pay for the failed group again on every page.
                    self._disabled_group_contexts.add((self.url, self.model))
                    values = [self._translate_single(text) for text in group]
                    requests_count += len(group)
            for text, value in zip(group, values):
                resolved[text] = value
                # Never cache a network failure / source-text fallback.
                if value != text and self._valid_translation(value):
                    self._cache.put((context, text), value)
        for i, text in enumerate(texts, 1):
            log.info('  -> [%d/%d] %s ==> %s', i, len(texts), text, resolved[text])
        log.info('Перевод: реплик=%d, новых уникальных=%d, запросов=%d', len(texts), len(missing), requests_count)
        return [resolved[text] for text in texts]
