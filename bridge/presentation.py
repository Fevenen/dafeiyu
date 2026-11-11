"""Bounded, ordered speech queue with synthesis ahead of playback.

Acceptance means queued, not necessarily played. Status exposes the distinction.
"""

import asyncio
import copy
import json
import importlib
from contextvars import ContextVar
from collections import OrderedDict
from .speech import to_speech

_current_valid = ContextVar('speech_valid', default=None)


class ObsoleteSpeech(Exception):
    pass


class SpeechQueue:
    def __init__(self, synthesize, play, remove, capacity=16):
        self.synthesize, self.play, self.remove = synthesize, play, remove
        self.queue = asyncio.Queue(capacity)
        self.jobs = OrderedDict()
        self.worker = None
        self.synth_lock = asyncio.Lock()

    async def enqueue(self, key, text, valid=None):
        if key in self.jobs:
            if self.jobs[key]["text"] != text:
                raise ValueError("job_id already belongs to different text")
            return self.jobs[key]["status"]
        if self.queue.full():
            raise asyncio.QueueFull

        async def generate():
            async with self.synth_lock:
                task = asyncio.create_task(self.synthesize(to_speech(text)))
                try:
                    return await asyncio.shield(task)
                except asyncio.CancelledError:
                    path = await task
                    if path:
                        self.remove(path)
                    raise

        job = {
            "key": key,
            "text": text,
            "status": "queued",
            "audio": asyncio.create_task(generate()),
            "valid": valid,
        }
        self.jobs[key] = job
        self.queue.put_nowait(job)
        if self.worker is None or self.worker.done():
            self.worker = asyncio.create_task(self.run())
        return "queued"

    async def run(self):
        while not self.queue.empty():
            job = await self.queue.get()
            path = None
            token = _current_valid.set(job['valid'])
            try:
                path = await job["audio"]
                if job['valid'] and not job['valid']():
                    raise ObsoleteSpeech()
                job["status"] = "playing"
                await self.play(job["text"], path)
                job["status"] = "played"
            except ObsoleteSpeech:
                job['status'] = 'cancelled'
            except asyncio.CancelledError:
                job["status"] = "cancelled"
                return
            except Exception:
                job["status"] = "failed"
            finally:
                _current_valid.reset(token)
                if path:
                    self.remove(path)
                self.queue.task_done()
                # Bound status retention without evicting active jobs.
                for key in list(self.jobs)[:-200]:
                    if self.jobs[key]["status"] in ("played", "failed", "cancelled"):
                        del self.jobs[key]

    async def close(self):
        # Let synthesis settle before cleanup (to_thread cannot stop a native engine).
        if self.worker and not self.worker.done():
            self.worker.cancel()
            await asyncio.gather(self.worker, return_exceptions=True)
        while not self.queue.empty():
            job = self.queue.get_nowait()
            try:
                path = await job["audio"]
                if path:
                    self.remove(path)
            except Exception:
                pass
            job["status"] = "cancelled"
            self.queue.task_done()


class CachedEngine:
    def __init__(self, path):
        self.path = path

    async def async_generate_audio(self, **kwargs):
        return self.path

    def remove_file(self, path):
        pass  # The queue owns the prefetched file.


async def enqueue(handler, text, key, valid=None):
    # run_server.py imports src.open_llm_vtuber; installed packages may omit src.
    # Resolve from the actual handler so there is only one backend module instance.
    package = type(handler).__module__.rsplit(".", 1)[0]
    _speak_forced = importlib.import_module(
        package + ".conversations.single_conversation"
    )._speak_forced
    TTSTaskManager = importlib.import_module(
        package + ".conversations.tts_manager"
    ).TTSTaskManager

    if not hasattr(handler, "_speech_queues"):
        handler._speech_queues = {}
        handler._speech_engine_locks = {}
    accepted = 0
    for uid, ws in list(handler.client_connections.items()):
        ctx = handler.client_contexts.get(uid)
        if ctx is None:
            continue
        if uid not in handler._speech_queues:

            async def synth(text, _ctx=ctx):
                lock = handler._speech_engine_locks.setdefault(
                    id(_ctx.tts_engine), asyncio.Lock()
                )
                async with lock:
                    return await _ctx.tts_engine.async_generate_audio(text=text)

            async def play(text, path, _ctx=ctx, _ws=ws, _uid=uid):
                task = handler.current_conversation_tasks.get(_uid)
                if task and not task.done():
                    # Preserve real conversations; wait instead of cancelling after 2s.
                    await task
                guard = _current_valid.get()
                if guard and not guard():
                    raise ObsoleteSpeech()
                clone = copy.copy(_ctx)
                clone.tts_engine = CachedEngine(path)
                manager = TTSTaskManager()
                try:
                    await asyncio.wait_for(
                        _speak_forced(clone, _ws.send_text, manager, _uid, text),
                        timeout=180,
                    )
                finally:
                    manager.clear()

            handler._speech_queues[uid] = SpeechQueue(
                synth, play, ctx.tts_engine.remove_file
            )
        await handler._speech_queues[uid].enqueue(key, text, valid=valid)
        accepted += 1
    return accepted


async def cancel(handler):
    for queue in getattr(handler, "_speech_queues", {}).values():
        await queue.close()
    for ws in list(handler.client_connections.values()):
        await ws.send_text(json.dumps({"type": "interrupt-signal"}))


def status(handler, key):
    return {
        uid: queue.jobs.get(key, {}).get("status", "unknown")
        for uid, queue in getattr(handler, "_speech_queues", {}).items()
    }
