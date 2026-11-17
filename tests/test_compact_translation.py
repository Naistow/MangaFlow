import unittest
from unittest.mock import Mock, patch
from core.translator.llm_service import MangaLLMTranslator


class CompactTranslationTests(unittest.TestCase):
    def test_overflow_request_is_separate_and_uses_existing_model(self):
        translator = MangaLLMTranslator(model='test-model', url='http://localhost:11434/api/chat')
        response = Mock()
        response.json.return_value = {'message': {'content': '{"bubbles": ["Лицо красное. Жар?"]}'}}
        with patch('core.translator.llm_service.requests.Session.post', return_value=response) as post:
            result = translator.compact_bubble_translation('顔が赤い', 'Длинный перевод', 30, 8)
        self.assertEqual('Лицо красное. Жар?', result)
        payload = post.call_args.kwargs['json']
        self.assertEqual('test-model', payload['model'])
        self.assertFalse(payload['stream'])
        self.assertIn('maximum_total_characters', payload['messages'][-1]['content'])
        response.raise_for_status.assert_called_once()

    def test_invalid_response_does_not_replace_translation(self):
        response = Mock()
        response.json.return_value = {'message': {'content': '{}'}}
        with patch('core.translator.llm_service.requests.Session.post', return_value=response):
            self.assertIsNone(MangaLLMTranslator().compact_bubble_translation('原文', 'Перевод', 30, 8))


if __name__ == '__main__':
    unittest.main()
