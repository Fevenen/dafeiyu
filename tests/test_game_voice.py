"""Run actual voice turn and LLM adapter code with synthetic ASR/model/audio endpoints."""
import ast
import asyncio
import json
from contextlib import ExitStack
from pathlib import Path
import tempfile
from types import MethodType, SimpleNamespace
import unittest
from unittest.mock import AsyncMock, Mock, patch

from bridge import settings
from bridge.game_context import conversation_context
from bridge.games.sillytavern import TavernService, digest

RUNTIME = Path(__file__).resolve().parents[1] / 'runtime/open_llm_vtuber'


def load_function(path, name, namespace):
    tree = ast.parse(path.read_text(encoding='utf-8-sig'))
    function = next(node for node in ast.walk(tree) if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) and node.name == name)
    module = ast.Module(body=[ast.ImportFrom(module='__future__', names=[ast.alias(name='annotations')], level=0), function], type_ignores=[])
    exec(compile(ast.fix_missing_locations(module), str(path), 'exec'), namespace)
    return namespace[name]


class VoiceSharedTests(unittest.IsolatedAsyncioTestCase):
    async def test_audio_transcription_turn_receives_tavern_context_and_shares_its_answer(self):
        class AudioInput:
            pass
        class Sentence:
            def __init__(self, text):
                self.text = text
        async def chunks():
            yield SimpleNamespace(choices=[SimpleNamespace(delta=SimpleNamespace(content='主人先问K删哪段记忆。'))])
        stream = chunks()
        class Stream:
            def __aiter__(self):
                return stream
            async def close(self):
                await stream.aclose()
        create = AsyncMock(return_value=Stream())
        llm = SimpleNamespace(support_tools=False, model='fixture', temperature=.6,
                              client=SimpleNamespace(chat=SimpleNamespace(completions=SimpleNamespace(create=create))))
        llm_namespace = {'NOT_GIVEN': object(), 'logger': Mock(),
                         'APIConnectionError': type('APIConnectionError', (Exception,), {}),
                         'RateLimitError': type('RateLimitError', (Exception,), {}),
                         'APIError': type('APIError', (Exception,), {})}
        llm_path = RUNTIME / 'agent/stateless_llm/openai_compatible_llm.py'
        load_function(llm_path, '_messages_for_log', llm_namespace)
        llm_function = load_function(llm_path, 'chat_completion', llm_namespace)
        llm.chat_completion = MethodType(llm_function, llm)
        class Agent:
            _memory = []
            async def chat(self, batch):
                answer = ''
                async for text in llm.chat_completion([{'role': 'user', 'content': batch.input_text}], '你是大肥鱼。'):
                    answer += text
                yield Sentence(answer)
        namespace = {'asyncio': asyncio, 'json': json, 'ExitStack': ExitStack, 'logger': Mock(), 'TTSTaskManager': Mock(),
                     'np': SimpleNamespace(ndarray=AudioInput, random=SimpleNamespace(choice=lambda _: 'test')),
                     'EMOJI_LIST': ['test'], 'send_conversation_start_signals': AsyncMock(),
                     'create_batch_input': lambda **data: SimpleNamespace(**data), 'store_message': Mock(),
                     'SentenceOutput': Sentence, 'AudioOutput': type('AudioOutput', (), {}),
                     'process_agent_output': AsyncMock(side_effect=lambda **data: data['output'].text),
                     'finalize_conversation_turn': AsyncMock(), 'cleanup_conversation': Mock()}
        namespace['process_user_input'] = load_function(RUNTIME / 'conversations/conversation_utils.py', 'process_user_input', namespace)
        turn = load_function(RUNTIME / 'conversations/single_conversation.py', 'process_single_conversation', namespace)
        with tempfile.TemporaryDirectory(prefix='pet-voice-context-') as temporary, patch.object(settings, 'DATA_DIR', Path(temporary)):
            service = TavernService()
            origin = 'http://127.0.0.1:8000'
            token = service.connect(origin)['token']
            service.set_mode(token, origin, 'companion')
            rows = [{'role': 'assistant', 'name': '主持人', 'text': '清除追踪需要删除记忆，K正在催促。'}]
            service.sync(token, origin, {'chat_id': 'voice-fixture', 'messages': rows, 'fingerprints': [digest(rows[0])]})
            service.shared.remember(conversation_context(), '先不要确认。', '本鲸也想先问清代价。', 'tavern')
            asr = SimpleNamespace(async_transcribe_np=AsyncMock(return_value='我后面该怎么做？'))
            context = SimpleNamespace(asr_engine=asr, agent_engine=Agent(), history_uid=None,
                                      live2d_model=None, tts_engine=None, translate_engine=None,
                                      character_config=SimpleNamespace(human_name='主人', character_name='大肥鱼'))
            with patch('bridge.gate.handle', return_value=(False, '')):
                answer = await turn(context, AsyncMock(), 'fixture-client', AudioInput())
            asr.async_transcribe_np.assert_awaited_once()
            self.assertEqual(answer, '主人先问K删哪段记忆。', str(namespace['logger'].method_calls))
            sent = create.call_args.kwargs['messages']
            self.assertIn('K正在催促', sent[-2]['content'])
            self.assertIn('本鲸也想先问清代价', sent[-2]['content'])
            self.assertEqual(sent[-1]['content'], '我后面该怎么做？')
            exchange = conversation_context()['recent_companion_chat'][-1]
            self.assertEqual(exchange['source'], 'desktop')
            self.assertEqual(exchange['assistant'], answer)
