import json
import logging
from fastapi import APIRouter, WebSocket, WebSocketDisconnect

from agent.orchestrator import Orchestrator

logger = logging.getLogger(__name__)
ws_router = APIRouter()


@ws_router.websocket("/ws/{session_id}")
async def websocket_chat(websocket: WebSocket, session_id: str):
    """
    WebSocket endpoint for real-time bidirectional chat.

    Client sends:  {"message": "...", "skill": "assistant"}
    Server sends:  {"type": "token",  "content": "..."}   — streamed tokens
                   {"type": "done",   "content": "..."}   — final signal
                   {"type": "error",  "content": "..."}   — error
    """
    await websocket.accept()
    logger.info(f"WebSocket connected: session={session_id}")

    try:
        while True:
            raw = await websocket.receive_text()
            try:
                data = json.loads(raw)
            except json.JSONDecodeError:
                await websocket.send_json({"type": "error", "content": "Invalid JSON"})
                continue

            message = data.get("message", "").strip()
            skill = data.get("skill", "assistant")

            if not message:
                await websocket.send_json({"type": "error", "content": "Empty message"})
                continue

            orch = Orchestrator(session_id=session_id, skill=skill)
            full_response = ""

            try:
                async for token in orch.run_stream(message):
                    full_response += token
                    await websocket.send_json({"type": "token", "content": token})

                await websocket.send_json({"type": "done", "content": full_response})

            except Exception as e:
                logger.exception(f"ws agent error: {e}")
                await websocket.send_json({"type": "error", "content": str(e)})

    except WebSocketDisconnect:
        logger.info(f"WebSocket disconnected: session={session_id}")
    except Exception as e:
        logger.exception(f"WebSocket error: {e}")
