import asyncio
from datetime import datetime, timezone, timedelta
from types import SimpleNamespace
import unittest

from bridge.screen_observer import ScreenObserver
from bridge.screen_context import attach_screen, wants_screen


def frame(token='grant', when=None):
    return {'source': 'screen', 'data': 'data:image/png;base64,c3ludGhldGlj', 'mime_type': 'image/png',
            'metadata': {'permission_token': token, 'captured_at': when or datetime.now(timezone.utc).isoformat(),
                         'frame_id': 'synthetic', 'source_name': 'test', 'width': 800, 'height': 600}}


class ObserverTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.sent = []
        async def send(data):
            self.sent.append(data)
        self.connections = {'pet': SimpleNamespace(send_json=send), 'other': SimpleNamespace(send_json=send)}
        self.observer = ScreenObserver(self.connections)

    async def begin(self):
        self.observer.update('pet', {'enabled': True, 'permission_token': 'grant'})
        task = asyncio.create_task(self.observer.snapshot(timeout=.2))
        await asyncio.sleep(0)
        return task

    async def test_default_off_does_not_request_a_capture(self):
        self.assertEqual((await self.observer.snapshot())['status'], 'disabled')
        self.assertEqual(self.sent, [])

    async def test_explicit_closed_target_never_falls_back_to_another_pet(self):
        self.observer.update('other', {'enabled': True, 'permission_token': 'other-grant'})
        self.assertEqual((await self.observer.snapshot(uid='pet'))['status'], 'disabled')
        self.assertEqual(self.sent, [])

    async def test_request_requires_matching_client_and_current_grant(self):
        task = await self.begin()
        rid = self.sent[0]['request_id']
        self.observer.receive('other', {'request_id': rid, 'images': [frame()]})
        self.assertFalse(task.done())
        self.observer.receive('pet', {'request_id': rid, 'images': [frame()]})
        self.assertTrue((await task)['ok'])
        self.assertFalse(self.observer.pending)

    async def test_close_discards_a_capture_already_in_flight(self):
        task = await self.begin()
        self.observer.update('pet', {'enabled': False})
        self.observer.receive('pet', {'request_id': self.sent[0]['request_id'], 'images': [frame()]})
        self.assertEqual((await task)['status'], 'disabled')

    async def test_disconnect_cancels_pending_request(self):
        task = await self.begin()
        self.observer.remove('pet')
        self.assertEqual((await task)['status'], 'disconnected')

    async def test_stale_frame_is_rejected(self):
        task = await self.begin()
        old = (datetime.now(timezone.utc) - timedelta(minutes=1)).isoformat()
        self.observer.receive('pet', {'request_id': self.sent[0]['request_id'], 'images': [frame(when=old)]})
        self.assertEqual((await task)['status'], 'invalid_frame')

    async def test_timeout_is_bounded_and_multiple_viewers_are_not_guessed(self):
        self.observer.update('pet', {'enabled': True, 'permission_token': 'grant'})
        self.assertEqual((await self.observer.snapshot(timeout=.01))['status'], 'timeout')
        self.assertFalse(self.observer.pending)
        self.observer.update('other', {'enabled': True, 'permission_token': 'second'})
        self.assertEqual((await self.observer.snapshot())['status'], 'ambiguous')

    async def test_concurrent_requests_share_one_capture(self):
        first = await self.begin()
        second = asyncio.create_task(self.observer.snapshot(timeout=.2))
        await asyncio.sleep(0)
        self.assertEqual(len(self.sent), 1)
        self.observer.receive('pet', {'request_id': self.sent[0]['request_id'], 'images': [frame()]})
        self.assertTrue((await first)['ok'])
        self.assertTrue((await second)['ok'])


class ScreenContextTests(unittest.TestCase):
    def test_visual_question_detection_does_not_capture_normal_chat(self):
        for text in ('你看看我这个题目是干啥的', '你看不见吗', '看看这个报错', '屏幕上写着什么', '我在干什么'):
            self.assertTrue(wants_screen(text), text)
        for text in ('你好', '今天好累', '现在这个桌宠屏幕识别是怎么走的', '给小王发消息说你好'):
            self.assertFalse(wants_screen(text), text)

    def test_fresh_image_is_attached_only_to_current_user_message(self):
        body = {'messages': [{'role': 'user', 'content': 'previous'}, {'role': 'assistant', 'content': 'old reply'},
                             {'role': 'user', 'content': '你看看我这个题目是干啥的'}]}
        result, status = attach_screen(body, lambda: {'ok': True, 'frame': frame()})
        self.assertEqual(status, 'attached')
        self.assertEqual(result['messages'][-1]['content'][-1]['type'], 'image_url')
        self.assertEqual(body['messages'][-1]['content'], '你看看我这个题目是干啥的')
        self.assertEqual(result['messages'][:-1], body['messages'][:-1])

    def test_off_state_explains_switch_without_inventing_a_picture(self):
        result, status = attach_screen({'messages': [{'role': 'user', 'content': '你看不见吗'}]},
                                      lambda: {'ok': False, 'status': 'disabled'})
        self.assertEqual(status, 'disabled')
        self.assertNotIn('image_url', str(result))
        self.assertIn('屏幕开关当前关闭', str(result))

    def test_ordinary_chat_titles_existing_images_and_tool_continuations_never_fetch(self):
        def forbidden():
            self.fail('Unexpected screenshot request')
        for body in (
            {'messages': [{'role': 'user', 'content': '你好'}]},
            {'messages': [{'role': 'system', 'content': 'Generate a title'}, {'role': 'user', 'content': '看看屏幕'}]},
            {'messages': [{'role': 'user', 'content': '看看屏幕'}, {'role': 'tool', 'content': 'result'}]},
            {'messages': [{'role': 'user', 'content': [{'type': 'text', 'text': '看看屏幕'}, {'type': 'image_url', 'image_url': {'url': 'provided'}}]}]},
        ):
            attach_screen(body, forbidden)
