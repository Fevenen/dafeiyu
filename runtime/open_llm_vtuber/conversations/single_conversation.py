from typing import Union, List, Dict, Any, Optional
import asyncio
import json
from contextlib import ExitStack
from loguru import logger
import numpy as np

from .conversation_utils import (
    create_batch_input,
    process_agent_output,
    send_conversation_start_signals,
    process_user_input,
    finalize_conversation_turn,
    cleanup_conversation,
    EMOJI_LIST,
)
from .types import WebSocketSend
from .tts_manager import TTSTaskManager
from ..chat_history_manager import store_message
from ..service_context import ServiceContext

# Import necessary types from agent outputs
from ..agent.output_types import SentenceOutput, AudioOutput


async def process_single_conversation(
    context: ServiceContext,
    websocket_send: WebSocketSend,
    client_uid: str,
    user_input: Union[str, np.ndarray],
    images: Optional[List[Dict[str, Any]]] = None,
    session_emoji: str = np.random.choice(EMOJI_LIST),
    metadata: Optional[Dict[str, Any]] = None,
) -> str:
    """Process a single-user conversation turn

    Args:
        context: Service context containing all configurations and engines
        websocket_send: WebSocket send function
        client_uid: Client unique identifier
        user_input: Text or audio input from user
        images: Optional list of image data
        session_emoji: Emoji identifier for the conversation
        metadata: Optional metadata for special processing flags

    Returns:
        str: Complete response text
    """
    # Create TTSTaskManager for this conversation
    tts_manager = TTSTaskManager()
    full_response = ""  # Initialize full_response here
    game_scope = ExitStack()
    response_ok = False

    try:
        # Send initial signals
        await send_conversation_start_signals(websocket_send)
        logger.info(f"New Conversation Chain {session_emoji} started!")

        # Process user input
        input_text = await process_user_input(
            user_input, context.asr_engine, websocket_send
        )
        from bridge.game_context import game_turn, remember_reply
        game_scope.enter_context(game_turn('desktop'))

        # Create batch input
        batch_input = create_batch_input(
            input_text=input_text,
            images=images,
            from_name=context.character_config.human_name,
            metadata=metadata,
        )

        # Store user message (check if we should skip storing to history)
        skip_history = metadata and metadata.get("skip_history", False)
        if context.history_uid and not skip_history:
            store_message(
                conf_uid=context.character_config.conf_uid,
                history_uid=context.history_uid,
                role="human",
                content=input_text,
                name=context.character_config.human_name,
            )

        if skip_history:
            logger.debug("Skipping storing user input to history (proactive speak)")

        logger.info(f"User input: {input_text}")
        if images:
            logger.info(f"With {len(images)} images")

        # ---- 统一路由：确定性操作先处理，未命中再做语义分类 ----
        forced_reply = None
        try:
            from bridge import gate as _confirm_gate  # 桌宠项目根目录在 sys.path 上

            from bridge.context import scope
            with scope("desktop:" + client_uid, text=input_text):
                handled, reply = await asyncio.to_thread(
                    _confirm_gate.handle, input_text,
                    recent_messages=list(getattr(context.agent_engine, '_memory', None) or []),
                )
            if handled and reply:
                forced_reply = reply
                logger.info(f"确认闸门处理：{reply}")
        except Exception as e:
            logger.warning(f"桌宠路由失败：{type(e).__name__}")
            forced_reply = "这次操作判断暂时失败，没有执行操作，请重试。"

        if forced_reply:
            speech_text = forced_reply
            try:
                from bridge import speech as _speech

                speech_text = _speech.to_speech(forced_reply)
            except Exception as e:
                logger.debug(f"语音转写跳过：{e}")
            await _speak_forced(
                context, websocket_send, tts_manager, client_uid, forced_reply, speech_text
            )
            return forced_reply

        try:
            # agent.chat yields Union[SentenceOutput, Dict[str, Any]]
            agent_output_stream = context.agent_engine.chat(batch_input)

            async for output_item in agent_output_stream:
                if (
                    isinstance(output_item, dict)
                    and output_item.get("type") == "tool_call_status"
                ):
                    # Handle tool status event: send WebSocket message
                    output_item["name"] = context.character_config.character_name
                    logger.debug(f"Sending tool status update: {output_item}")

                    await websocket_send(json.dumps(output_item))

                elif isinstance(output_item, (SentenceOutput, AudioOutput)):
                    # Handle SentenceOutput or AudioOutput
                    response_part = await process_agent_output(
                        output=output_item,
                        character_config=context.character_config,
                        live2d_model=context.live2d_model,
                        tts_engine=context.tts_engine,
                        websocket_send=websocket_send,  # Pass websocket_send for audio/tts messages
                        tts_manager=tts_manager,
                        translate_engine=context.translate_engine,
                    )
                    # Ensure response_part is treated as a string before concatenation
                    response_part_str = (
                        str(response_part) if response_part is not None else ""
                    )
                    full_response += response_part_str  # Accumulate text response
                else:
                    logger.warning(
                        f"Received unexpected item type from agent chat stream: {type(output_item)}"
                    )
                    logger.debug(f"Unexpected item content: {output_item}")

            response_ok = True
        except Exception as e:
            logger.exception(
                f"Error processing agent response stream: {e}"
            )  # Log with stack trace
            await websocket_send(
                json.dumps(
                    {
                        "type": "error",
                        "message": f"Error processing agent response: {str(e)}",
                    }
                )
            )
            # full_response will contain partial response before error
        # --- End processing agent response ---

        await finalize_conversation_turn(
            tts_manager=tts_manager,
            websocket_send=websocket_send,
            client_uid=client_uid,
        )

        if context.history_uid and full_response:  # Check full_response before storing
            store_message(
                conf_uid=context.character_config.conf_uid,
                history_uid=context.history_uid,
                role="ai",
                content=full_response,
                name=context.character_config.character_name,
                avatar=context.character_config.avatar,
            )
            logger.info(f"AI response: {full_response}")

        if response_ok:
            remember_reply(input_text, full_response)
        return full_response  # Return accumulated full_response

    except asyncio.CancelledError:
        logger.info(f"🤡👍 Conversation {session_emoji} cancelled because interrupted.")
        raise
    except Exception as e:
        logger.opt(exception=True).error(f"Error in conversation chain: {e}")
        await websocket_send(
            json.dumps({"type": "error", "message": f"Conversation error: {str(e)}"})
        )
        raise
    finally:
        game_scope.close()
        cleanup_conversation(tts_manager, session_emoji)


async def _speak_forced(
    context: ServiceContext,
    websocket_send: WebSocketSend,
    tts_manager: TTSTaskManager,
    client_uid: str,
    text: str,
    speech_text: Optional[str] = None,
) -> None:
    """让桌宠直接说一句话（不经过模型），走正常的 TTS + 表情链路。

    text 用于显示，speech_text 用于念（英文名、QQ 号会被转写成中文读法）。
    """
    from ..agent.output_types import Actions, DisplayText
    await send_conversation_start_signals(websocket_send)

    # 没显式给念法时，默认过一遍 bridge.speech：
    # 删动作括号、英文/数字转中文读法（只影响"念"，不影响显示）
    if not speech_text:
        try:
            from bridge.speech import to_speech as _to_speech

            speech_text = _to_speech(text)
        except Exception:
            speech_text = text

    output = SentenceOutput(
        display_text=DisplayText(
            text=text,
            name=context.character_config.character_name,
            avatar=context.character_config.avatar,
        ),
        tts_text=speech_text,
        actions=Actions(),
    )
    await process_agent_output(
        output=output,
        character_config=context.character_config,
        live2d_model=context.live2d_model,
        tts_engine=context.tts_engine,
        websocket_send=websocket_send,
        tts_manager=tts_manager,
        translate_engine=context.translate_engine,
    )
    await finalize_conversation_turn(
        tts_manager=tts_manager,
        websocket_send=websocket_send,
        client_uid=client_uid,
    )
