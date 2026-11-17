import json
import unittest
from unittest.mock import Mock, patch
import requests
from core.translator.llm_service import MangaLLMTranslator


def reply(entries):
    response = Mock()
    response.json.return_value = {'message': {'content': json.dumps({'bubbles': entries})}}
    return response


class TranslationPerformanceTests(unittest.TestCase):
    def setUp(self):
        self.translator = MangaLLMTranslator(model='gemma2:9b')
        self.addCleanup(self.translator.session.close)

    def test_four_lines_use_one_request_and_ids_restore_order(self):
        response = reply([{'id': 3, 'text': 'Четыре'}, {'id': 0, 'text': 'Один'},
                          {'id': 2, 'text': 'Три'}, {'id': 1, 'text': 'Два'}])
        with patch.object(self.translator.session, 'post', return_value=response) as post:
            result = self.translator.translate_bubbles_batch(['一', '二', '三', '四'])
        self.assertEqual(['Один', 'Два', 'Три', 'Четыре'], result)
        self.assertEqual(1, post.call_count)
        self.assertEqual('gemma2:9b', post.call_args.kwargs['json']['model'])
        self.assertEqual(1024, post.call_args.kwargs['json']['options']['num_ctx'])

    def test_cache_and_duplicates_make_no_extra_requests(self):
        with patch.object(self.translator.session, 'post', return_value=reply(['Привет'])) as post:
            self.assertEqual(['Привет', 'Привет'], self.translator.translate_bubbles_batch(['こんにちは', 'こんにちは']))
            self.assertEqual(['Привет'], self.translator.translate_bubbles_batch(['こんにちは']))
            self.assertEqual(1, post.call_count)

    def test_invalid_group_falls_back_without_losing_lines(self):
        invalid = reply([{'id': 0, 'text': 'Первый'}, {'id': 0, 'text': 'Дубликат'}])
        with patch.object(self.translator.session, 'post', side_effect=[invalid, reply(['Да']), reply(['Нет'])]) as post:
            self.assertEqual(['Да', 'Нет'], self.translator.translate_bubbles_batch(['はい', 'いいえ']))
            self.assertEqual(3, post.call_count)

    def test_server_failure_is_not_cached_and_does_not_cascade_timeouts(self):
        with patch.object(self.translator.session, 'post', side_effect=requests.ConnectionError('offline')) as post:
            self.assertEqual(['一', '二'], self.translator.translate_bubbles_batch(['一', '二']))
            self.assertEqual(1, post.call_count)
        with patch.object(self.translator.session, 'post', return_value=reply([
                {'id': 0, 'text': 'Один'}, {'id': 1, 'text': 'Два'}])) as post:
            self.assertEqual(['Один', 'Два'], self.translator.translate_bubbles_batch(['一', '二']))
            self.assertEqual(1, post.call_count)

    def test_model_change_invalidates_cached_translation(self):
        with patch.object(self.translator.session, 'post', return_value=reply(['Да'])) as post:
            self.translator.translate_bubbles_batch(['はい'])
            self.translator.model = 'same-family-new-tag'
            self.translator.translate_bubbles_batch(['はい'])
            self.assertEqual(2, post.call_count)

    def test_group_size_and_prompt_size_remain_bounded(self):
        source = ['あ' * 110, 'い' * 110, 'う' * 110]
        with patch.object(self.translator.session, 'post', return_value=reply(['Тест'])) as post:
            self.assertEqual(['Тест'] * 3, self.translator.translate_bubbles_batch(source))
            self.assertEqual(3, post.call_count)

    def test_http_group_failure_recovers_with_small_requests(self):
        failed = Mock(status_code=500)
        error = requests.HTTPError('server error', response=failed)
        with patch.object(self.translator.session, 'post', side_effect=[error, reply(['Да']), reply(['Нет'])]) as post:
            self.assertEqual(['Да', 'Нет'], self.translator.translate_bubbles_batch(['はい', 'いいえ']))
            self.assertEqual(3, post.call_count)
            self.assertIn((self.translator.url, self.translator.model), self.translator._disabled_group_contexts)

    def test_single_and_compaction_keep_same_runner_context(self):
        with patch.object(self.translator.session, 'post', return_value=reply(['Да'])) as post:
            self.translator.translate_bubbles_batch(['はい'])
            self.translator.compact_bubble_translation('はい', 'Конечно да', 10, 5)
        contexts = [call.kwargs['json']['options']['num_ctx'] for call in post.call_args_list]
        self.assertEqual([1024, 1024], contexts)

    def test_compaction_result_is_reused(self):
        with patch.object(self.translator.session, 'post', return_value=reply(['Да'])) as post:
            first = self.translator.compact_bubble_translation('はい', 'Конечно да', 10, 5)
            self.assertEqual(first, self.translator.compact_bubble_translation('はい', 'Конечно да', 10, 5))
            self.assertEqual(1, post.call_count)


if __name__ == '__main__':
    unittest.main()
