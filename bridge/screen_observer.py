"""On-demand screen RPC; only a connected client's current opt-in may grant pixels."""

import asyncio
from datetime import datetime
import time
import uuid


class ScreenObserver:
    def __init__(self, connections):
        self.connections = connections
        self.states = {}
        self.pending = {}
        self.inflight = {}

    def _revoke(self, uid, status='disabled'):
        for request in list(self.pending.values()):
            if request['uid'] == uid and not request['future'].done():
                request['future'].set_result({'ok': False, 'status': status})

    def update(self, uid, data):
        token = data.get('permission_token')
        enabled = data.get('enabled') is True and isinstance(token, str) and 0 < len(token) <= 160
        previous = self.states.get(uid)
        state = token if enabled else None
        self.states[uid] = state
        if previous != state or not enabled:
            self._revoke(uid)

    def remove(self, uid):
        self.states.pop(uid, None)
        self._revoke(uid, 'disconnected')

    def status(self):
        active = [uid for uid, token in self.states.items() if token and uid in self.connections]
        return {'ok': True, 'enabled': bool(active), 'active_clients': len(active)}

    async def snapshot(self, uid=None, timeout=4.0):
        active = [key for key, token in self.states.items() if token and key in self.connections]
        if uid:
            active = [key for key in active if key == uid]
        if not active:
            return {'ok': False, 'status': 'disabled'}
        if len(active) != 1:
            return {'ok': False, 'status': 'ambiguous'}
        uid = active[0]
        token = self.states[uid]
        key = (uid, token)
        request = self.inflight.get(key)
        if request is None:
            if len(self.pending) >= 4:
                return {'ok': False, 'status': 'busy'}
            rid = uuid.uuid4().hex
            request = {'uid': uid, 'token': token, 'id': rid,
                       'created': time.time(), 'future': asyncio.get_running_loop().create_future()}
            self.pending[rid] = request
            self.inflight[key] = request
            try:
                await self.connections[uid].send_json({
                    'type': 'screen-capture-request', 'request_id': rid, 'permission_token': token,
                })
            except Exception:
                self.remove(uid)
        try:
            result = await asyncio.wait_for(asyncio.shield(request['future']), timeout)
            if result.get('ok') and (self.states.get(uid) != token or uid not in self.connections):
                return {'ok': False, 'status': 'disabled'}
            return result
        except asyncio.TimeoutError:
            return {'ok': False, 'status': 'timeout'}
        finally:
            if self.inflight.get(key) is request:
                self.inflight.pop(key, None)
            self.pending.pop(request['id'], None)

    def receive(self, uid, data):
        request = self.pending.get(data.get('request_id'))
        if not request or request['uid'] != uid or request['future'].done():
            return
        if self.states.get(uid) != request['token'] or uid not in self.connections:
            return
        frames = data.get('images')
        frame = frames[0] if isinstance(frames, list) and len(frames) == 1 else None
        if not isinstance(frame, dict):
            request['future'].set_result({'ok': False, 'status': 'capture_failed'})
            return
        metadata = frame.get('metadata')
        pixels = frame.get('data')
        valid = (frame.get('source') == 'screen' and isinstance(metadata, dict)
                 and metadata.get('permission_token') == request['token']
                 and isinstance(pixels, str) and len(pixels) <= 12 * 1024 * 1024
                 and pixels.startswith(('data:image/png;base64,', 'data:image/jpeg;base64,')))
        if valid:
            try:
                captured = datetime.fromisoformat(str(metadata['captured_at']).replace('Z', '+00:00')).timestamp()
                valid = request['created'] - 1 <= captured <= time.time() + 5
            except (KeyError, TypeError, ValueError, OverflowError):
                valid = False
        request['future'].set_result({'ok': True, 'status': 'captured', 'frame': frame}
                                     if valid else {'ok': False, 'status': 'invalid_frame'})
