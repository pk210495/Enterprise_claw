import logging
from fastapi import APIRouter, HTTPException
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field

from agent.orchestrator import Orchestrator
from agent.session import SessionManager
from providers.registry import provider_registry
from skills.registry import list_all_skills
from config import config

logger = logging.getLogger(__name__)
router = APIRouter()

# ── Request / Response models ────────────────────────────────────────────────

class ChatRequest(BaseModel):
    session_id: str = Field(..., description="Unique session identifier")
    message: str    = Field(..., description="User message")
    skill: str      = Field("assistant", description="Skill to use for this session")


class ChatResponse(BaseModel):
    session_id: str
    reply: str
    message_count: int


class ClearRequest(BaseModel):
    session_id: str


# ── Chat endpoints ───────────────────────────────────────────────────────────

@router.post("/chat", response_model=ChatResponse, summary="Send a message and get a full response")
async def chat(req: ChatRequest):
    try:
        orch = Orchestrator(session_id=req.session_id, skill=req.skill)
        reply = await orch.run(req.message)
        return ChatResponse(
            session_id=req.session_id,
            reply=reply,
            message_count=orch._session.message_count,
        )
    except Exception as e:
        logger.exception(f"chat error: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/chat/stream", summary="Send a message and receive a streaming response (SSE)")
async def chat_stream(req: ChatRequest):
    async def generator():
        try:
            orch = Orchestrator(session_id=req.session_id, skill=req.skill)
            async for token in orch.run_stream(req.message):
                yield f"data: {token}\n\n"
            yield "data: [DONE]\n\n"
        except Exception as e:
            logger.exception(f"stream error: {e}")
            yield f"data: ERROR: {e}\n\n"

    return StreamingResponse(generator(), media_type="text/event-stream")


# ── Session endpoints ────────────────────────────────────────────────────────

@router.get("/sessions", summary="List all sessions")
async def list_sessions():
    return {"sessions": SessionManager.list_all()}


@router.get("/sessions/{session_id}/history", summary="Get full message history for a session")
async def get_history(session_id: str):
    session = SessionManager(session_id)
    return {
        "session_id": session_id,
        "message_count": session.message_count,
        "messages": session.get_history(),
    }


@router.delete("/sessions/{session_id}", summary="Clear and delete a session")
async def delete_session(session_id: str):
    session = SessionManager(session_id)
    session.clear()
    return {"status": "cleared", "session_id": session_id}


# ── File endpoints ───────────────────────────────────────────────────────────

@router.get("/files", summary="List all files in the workspace")
async def list_files():
    workspace = config.workspace.path
    if not workspace.exists():
        return {"files": []}
    files = []
    for f in sorted(workspace.rglob("*")):
        if f.is_file() and f.suffix in config.workspace.allowed_extensions:
            files.append({
                "path": str(f.relative_to(workspace)),
                "size_bytes": f.stat().st_size,
            })
    return {"files": files}


@router.get("/files/{file_path:path}", summary="Read a file from the workspace")
async def read_file(file_path: str):
    workspace = config.workspace.path.resolve()
    target = (workspace / file_path).resolve()
    if not str(target).startswith(str(workspace)):
        raise HTTPException(status_code=403, detail="Path outside workspace.")
    if not target.exists():
        raise HTTPException(status_code=404, detail=f"File not found: {file_path}")
    return {
        "path": file_path,
        "content": target.read_text(encoding="utf-8"),
    }


# ── Skills endpoints ─────────────────────────────────────────────────────────

@router.get("/skills", summary="List all available skills")
async def list_skills():
    return {"skills": list_all_skills()}


# ── Provider health endpoint ─────────────────────────────────────────────────

@router.get("/providers/status", summary="Get health status of all configured providers")
async def provider_status():
    statuses = await provider_registry.get_all_statuses()
    return {
        "providers": [
            {"name": name, "healthy": healthy}
            for name, healthy in statuses.items()
        ]
    }


# ── Health check ─────────────────────────────────────────────────────────────

@router.get("/health", summary="Server health check")
async def health():
    return {"status": "ok"}
