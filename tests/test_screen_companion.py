import asyncio
import unittest
from types import SimpleNamespace

from bridge.screen_companion import ScreenCompanion
from bridge.screen_observer import ScreenObserver
from test_screen_observer import frame


class ScreenCompanionTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.calls, self.speech = [], []
        self.now = 100
        self.tavern = False
        connections = {'pet': object(), 'other': object()}
        self.observer = ScreenObserver(connections)
        self.handler = SimpleNamespace(client_connections=connections, screen_observer=self.observer,
                                       current_conversation_tasks={}, tavern_is_active=lambda: self.tavern)
        self.companion = ScreenCompanion(self.handler, self.model, self.speak, lambda: self.now)
        self.observer.update('pet', {'enabled': True, 'permission_token': 'grant'})

    async def model(self, image, identity):
        self.calls.append(image)
        return '本鲸看见右边多了一枚棋子。'

    async def speak(self, handler, text, key, valid, target_uid):
        self.speech.append((text, target_uid, valid))

    def enable(self):
        self.companion.update('pet', {'enabled': True, 'permission_token': 'grant'})

    async def submit(self, token='grant'):
        self.companion.receive('pet', {'images': [frame(token)]})
        if job := self.companion.jobs.get('pet'):
            await job

    async def test_requires_both_switches_and_the_current_capture_grant(self):
        await self.submit()
        self.enable()
        await self.submit('old-grant')
        self.assertFalse(self.calls)
        await self.submit()
        self.assertEqual(len(self.calls), 1)
        self.assertEqual(self.speech[0][1], 'pet')
        self.assertTrue(self.speech[0][2]())
        self.observer.update('pet', {'enabled': False})
        self.assertFalse(self.speech[0][2]())

    async def test_defers_to_conversation_and_tavern_and_limits_requests(self):
        self.enable()
        self.tavern = True
        await self.submit()
        self.tavern = False
        busy = asyncio.get_running_loop().create_future()
        self.handler.current_conversation_tasks['pet'] = busy
        await self.submit()
        self.assertFalse(self.calls)
        busy.set_result(None)
        await self.submit()
        await self.submit()
        self.assertEqual(len(self.calls), 1)
        self.now += 45
        await self.submit()
        self.assertEqual(len(self.calls), 2)
        self.assertEqual(len(self.speech), 1)

    async def test_disable_discards_a_result_even_if_model_ignores_cancellation(self):
        started = asyncio.Event()

        async def late_model(image, identity):
            started.set()
            try:
                await asyncio.Future()
            except asyncio.CancelledError:
                return '不应播出。'

        self.companion.model = late_model
        self.enable()
        self.companion.receive('pet', {'images': [frame()]})
        job = self.companion.jobs['pet']
        await started.wait()
        self.companion.disable('pet')
        self.enable()
        await job
        self.assertFalse(self.speech)
