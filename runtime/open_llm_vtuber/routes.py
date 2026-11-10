import os
import json
from uuid import uuid4
import numpy as np
from datetime import datetime
from fastapi import APIRouter, WebSocket, UploadFile, File, Response
from starlette.responses import JSONResponse
from starlette.websockets import WebSocketDisconnect
from loguru import logger
from .service_context import ServiceContext
from .websocket_handler import WebSocketHandler
from .proxy_handler import ProxyHandler


def init_client_ws_route(default_context_cache: ServiceContext) -> APIRouter:
    """
    Create and return API routes for handling the `/client-ws` WebSocket connections.

    Args:
        default_context_cache: Default service context cache for new sessions.

    Returns:
        APIRouter: Configured router with WebSocket endpoint.
    """

    router = APIRouter()
    ws_handler = WebSocketHandler(default_context_cache)

    @router.get("/api/health")
    async def api_health():
        return {"ok": True, "bridge_version": "0.2.0", "speech_queue": True,
                "clients": len(ws_handler.client_connections)}

    @router.get("/api/speech/status")
    async def api_speech_status(job_id: str):
        from bridge.presentation import status
        return {"ok": True, "jobs": status(ws_handler, job_id)}

    @router.post("/api/speech/cancel")
    async def api_speech_cancel():
        from bridge.presentation import cancel
        await cancel(ws_handler)
        return {"ok": True}

    @router.websocket("/client-ws")
    async def websocket_endpoint(websocket: WebSocket):
        """WebSocket endpoint for client connections"""
        await websocket.accept()
        client_uid = str(uuid4())

        try:
            await ws_handler.handle_new_connection(websocket, client_uid)
            await ws_handler.handle_websocket_communication(websocket, client_uid)
        except WebSocketDisconnect:
            await ws_handler.handle_disconnect(client_uid)
        except Exception as e:
            logger.error(f"Error in WebSocket connection: {e}")
            await ws_handler.handle_disconnect(client_uid)
            raise

    @router.post("/api/proactive")
    async def api_proactive(payload: dict):
        """外部（提醒守护进程）让桌宠主动说一句话。"""
        text = (payload or {}).get("text", "")
        if not text:
            return JSONResponse({"ok": False, "error": "text 为空"}, status_code=400)
        try:
            n = await ws_handler.proactive_speak(text, str(payload.get("client_uid") or ""))
            return JSONResponse({"ok": True, "clients": n})
        except Exception as e:
            logger.error(f"/api/proactive 失败：{e}")
            return JSONResponse({"ok": False, "error": str(e)}, status_code=500)

    @router.post("/api/chat")
    async def api_chat(payload: dict):
        """外部往对话里发一句话，等于用户在桌宠窗口里打字（走模型）。"""
        text = (payload or {}).get("text", "")
        if not text:
            return JSONResponse({"ok": False, "error": "text 为空"}, status_code=400)
        try:
            n = await ws_handler.proactive_speak(text, str(payload.get("client_uid") or ""))
            return JSONResponse({"ok": True, "clients": n})
        except Exception as e:
            logger.error(f"/api/chat 失败：{e}")
            return JSONResponse({"ok": False, "error": str(e)}, status_code=500)

    @router.post("/api/say")
    async def api_say(payload: dict):
        """外部给一句话，桌宠直接念出来（不经过模型）。"""
        text = (payload or {}).get("text", "")
        if not text:
            return JSONResponse({"ok": False, "error": "text 为空"}, status_code=400)
        try:
            if payload.get("enqueue"):
                import asyncio
                from bridge.presentation import enqueue
                key = str(payload.get("job_id") or uuid4().hex)
                try:
                    n = await enqueue(ws_handler, text, key)
                except asyncio.QueueFull:
                    return JSONResponse({"ok": False, "error": "speech queue full"}, status_code=429)
                except ValueError as error:
                    return JSONResponse({"ok": False, "error": str(error)}, status_code=409)
                return JSONResponse({"ok": True, "clients": n, "job_id": key, "status": "queued"})
            n = await ws_handler.say_now(text)
            return JSONResponse({"ok": True, "clients": n})
        except Exception as e:
            logger.error(f"/api/say 失败：{e}")
            return JSONResponse({"ok": False, "error": str(e)}, status_code=500)

    @router.get("/api/transcript")
    async def api_transcript(limit: int = 50):
        """最近 N 条对话（从 chat_history 里读最新那份）。"""
        try:
            conf_uid = default_context_cache.character_config.conf_uid
            folder = os.path.join("chat_history", conf_uid)
            if not os.path.isdir(folder):
                return JSONResponse({"ok": True, "messages": []})
            files = [
                os.path.join(folder, f)
                for f in os.listdir(folder)
                if f.endswith(".json")
            ]
            if not files:
                return JSONResponse({"ok": True, "messages": []})
            newest = max(files, key=os.path.getmtime)
            with open(newest, encoding="utf-8") as f:
                data = json.load(f)
            msgs = [
                {
                    "role": m.get("role"),
                    "name": m.get("name", ""),
                    "content": m.get("content", ""),
                    "timestamp": m.get("timestamp", ""),
                }
                for m in data
                if m.get("role") in ("human", "ai")
            ]
            return JSONResponse({"ok": True, "messages": msgs[-max(1, limit):]})
        except Exception as e:
            logger.error(f"/api/transcript 失败：{e}")
            return JSONResponse({"ok": False, "error": str(e)}, status_code=500)

    return router


def init_proxy_route(server_url: str) -> APIRouter:
    """
    Create and return API routes for handling proxy connections.

    Args:
        server_url: The WebSocket URL of the actual server

    Returns:
        APIRouter: Configured router with proxy WebSocket endpoint
    """
    router = APIRouter()
    proxy_handler = ProxyHandler(server_url)

    @router.websocket("/proxy-ws")
    async def proxy_endpoint(websocket: WebSocket):
        """WebSocket endpoint for proxy connections"""
        try:
            await proxy_handler.handle_client_connection(websocket)
        except Exception as e:
            logger.error(f"Error in proxy connection: {e}")
            raise

    return router


def init_webtool_routes(default_context_cache: ServiceContext) -> APIRouter:
    """
    Create and return API routes for handling web tool interactions.

    Args:
        default_context_cache: Default service context cache for new sessions.

    Returns:
        APIRouter: Configured router with WebSocket endpoint.
    """

    router = APIRouter()

    @router.get("/web-tool")
    async def web_tool_redirect():
        """Redirect /web-tool to /web_tool/index.html"""
        return Response(status_code=302, headers={"Location": "/web-tool/index.html"})

    @router.get("/web_tool")
    async def web_tool_redirect_alt():
        """Redirect /web_tool to /web_tool/index.html"""
        return Response(status_code=302, headers={"Location": "/web-tool/index.html"})

    @router.get("/live2d-models/info")
    async def get_live2d_folder_info():
        """Get information about available Live2D models"""
        live2d_dir = "live2d-models"
        if not os.path.exists(live2d_dir):
            return JSONResponse(
                {"error": "Live2D models directory not found"}, status_code=404
            )

        valid_characters = []
        supported_extensions = [".png", ".jpg", ".jpeg"]

        for entry in os.scandir(live2d_dir):
            if entry.is_dir():
                folder_name = entry.name.replace("\\", "/")
                model3_file = os.path.join(
                    live2d_dir, folder_name, f"{folder_name}.model3.json"
                ).replace("\\", "/")

                if os.path.isfile(model3_file):
                    # Find avatar file if it exists
                    avatar_file = None
                    for ext in supported_extensions:
                        avatar_path = os.path.join(
                            live2d_dir, folder_name, f"{folder_name}{ext}"
                        )
                        if os.path.isfile(avatar_path):
                            avatar_file = avatar_path.replace("\\", "/")
                            break

                    valid_characters.append(
                        {
                            "name": folder_name,
                            "avatar": avatar_file,
                            "model_path": model3_file,
                        }
                    )
        return JSONResponse(
            {
                "type": "live2d-models/info",
                "count": len(valid_characters),
                "characters": valid_characters,
            }
        )

    @router.post("/asr")
    async def transcribe_audio(file: UploadFile = File(...)):
        """
        Endpoint for transcribing audio using the ASR engine
        """
        logger.info(f"Received audio file for transcription: {file.filename}")

        try:
            contents = await file.read()

            # Validate minimum file size
            if len(contents) < 44:  # Minimum WAV header size
                raise ValueError("Invalid WAV file: File too small")

            # Decode the WAV header and get actual audio data
            wav_header_size = 44  # Standard WAV header size
            audio_data = contents[wav_header_size:]

            # Validate audio data size
            if len(audio_data) % 2 != 0:
                raise ValueError("Invalid audio data: Buffer size must be even")

            # Convert to 16-bit PCM samples to float32
            try:
                audio_array = (
                    np.frombuffer(audio_data, dtype=np.int16).astype(np.float32)
                    / 32768.0
                )
            except ValueError as e:
                raise ValueError(
                    f"Audio format error: {str(e)}. Please ensure the file is 16-bit PCM WAV format."
                )

            # Validate audio data
            if len(audio_array) == 0:
                raise ValueError("Empty audio data")

            text = await default_context_cache.asr_engine.async_transcribe_np(
                audio_array
            )
            logger.info(f"Transcription result: {text}")
            return {"text": text}

        except ValueError as e:
            logger.error(f"Audio format error: {e}")
            return Response(
                content=json.dumps({"error": str(e)}),
                status_code=400,
                media_type="application/json",
            )
        except Exception as e:
            logger.error(f"Error during transcription: {e}")
            return Response(
                content=json.dumps(
                    {"error": "Internal server error during transcription"}
                ),
                status_code=500,
                media_type="application/json",
            )

    @router.websocket("/tts-ws")
    async def tts_endpoint(websocket: WebSocket):
        """WebSocket endpoint for TTS generation"""
        await websocket.accept()
        logger.info("TTS WebSocket connection established")

        try:
            while True:
                data = await websocket.receive_json()
                text = data.get("text")
                if not text:
                    continue

                logger.info(f"Received text for TTS: {text}")

                # Split text into sentences
                sentences = [s.strip() for s in text.split(".") if s.strip()]

                try:
                    # Generate and send audio for each sentence
                    for sentence in sentences:
                        sentence = sentence + "."  # Add back the period
                        file_name = f"{datetime.now().strftime('%Y%m%d_%H%M%S')}_{str(uuid4())[:8]}"
                        audio_path = (
                            await default_context_cache.tts_engine.async_generate_audio(
                                text=sentence, file_name_no_ext=file_name
                            )
                        )
                        logger.info(
                            f"Generated audio for sentence: {sentence} at: {audio_path}"
                        )

                        await websocket.send_json(
                            {
                                "status": "partial",
                                "audioPath": audio_path,
                                "text": sentence,
                            }
                        )

                    # Send completion signal
                    await websocket.send_json({"status": "complete"})

                except Exception as e:
                    logger.error(f"Error generating TTS: {e}")
                    await websocket.send_json({"status": "error", "message": str(e)})

        except WebSocketDisconnect:
            logger.info("TTS WebSocket client disconnected")
        except Exception as e:
            logger.error(f"Error in TTS WebSocket connection: {e}")
            await websocket.close()

    return router
