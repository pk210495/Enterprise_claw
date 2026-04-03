"""
Python Agent Server
───────────────────
FastAPI-based agentic orchestration server.
Provider-agnostic · Parallel subagents · Enterprise security · Skills · Memory · Soul
"""

import hashlib
import logging
import os
import stat
import sys
from contextlib import asynccontextmanager
from pathlib import Path

import uvicorn
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse

from api.routes import router
from api.websocket import ws_router
from config import config

# ── Logging ──────────────────────────────────────────────────────────────────
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s  %(levelname)-8s  %(name)s  %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)
logger = logging.getLogger(__name__)


# ═══════════════════════════════════════════════════════════════════════════
#  STARTUP CHECKS
# ═══════════════════════════════════════════════════════════════════════════

def enforce_security_permissions():
    """
    Ensure Security.md exists and is read-only at the OS level (chmod 444).
    Server refuses to start if the file is missing.
    """
    path = config.security_path

    if not path.exists():
        logger.critical("━" * 60)
        logger.critical("STARTUP FAILED: storage/security/Security.md not found.")
        logger.critical("The server cannot start without the organisational constitution.")
        logger.critical("Create Security.md then restart.")
        logger.critical("━" * 60)
        sys.exit(1)

    # set read-only on all platforms
    try:
        os.chmod(path, stat.S_IRUSR | stat.S_IRGRP | stat.S_IROTH)  # 444
        logger.info("Security.md permissions enforced (read-only)")
    except Exception as e:
        logger.warning(f"Could not set Security.md permissions: {e}")


def check_security_integrity():
    """
    SHA-256 hash verification of Security.md.
    On first run: writes the hash file.
    On subsequent runs: verifies the file has not changed.
    If mismatch → server refuses to start (admin must re-sign).
    """
    sec_path  = config.security_path
    hash_path = config.security_hash_path

    current_hash = hashlib.sha256(sec_path.read_bytes()).hexdigest()

    if hash_path.exists():
        stored_hash = hash_path.read_text().strip()
        if current_hash != stored_hash:
            logger.critical("━" * 60)
            logger.critical("INTEGRITY VIOLATION: Security.md has been modified since last verified.")
            logger.critical("Server will not start. Review changes and re-sign:")
            logger.critical("  python -c \"")
            logger.critical("    import hashlib; from pathlib import Path")
            logger.critical("    p = Path('storage/security/Security.md')")
            logger.critical("    Path('storage/security/Security.md.sha256').write_text(")
            logger.critical("        hashlib.sha256(p.read_bytes()).hexdigest())")
            logger.critical("    print('Re-signed.')\"")
            logger.critical("━" * 60)
            sys.exit(1)
        logger.info("Security.md integrity verified ✓")
    else:
        hash_path.write_text(current_hash)
        logger.info(f"Security.md hash written (first run): {current_hash[:16]}...")


def ensure_directories():
    """Create required directories if they don't exist."""
    dirs = [
        config.sessions_dir,
        config.memory_dir,
        config.workspace.path,
        config.custom_skills_dir,
        config.security_path.parent,
        config.soul_path.parent,
        config.plans_dir,
        config.bus_dir,
    ]
    for d in dirs:
        d.mkdir(parents=True, exist_ok=True)
    logger.info("Storage directories verified")


def check_soul():
    if not config.soul_path.exists():
        logger.warning("storage/soul/boot.md not found — agent will have no soul/identity. Creating placeholder.")
        config.soul_path.write_text(
            "# Agent Identity\n\nYou are a helpful, precise, and direct AI assistant.\n",
            encoding="utf-8",
        )


async def warmup_providers():
    """Ping all enabled providers and log their status."""
    from providers.registry import provider_registry
    statuses = await provider_registry.get_all_statuses()
    for name, healthy in statuses.items():
        icon = "✓" if healthy else "✗"
        level = logging.INFO if healthy else logging.WARNING
        logger.log(level, f"  provider {icon}  {name}")


# ═══════════════════════════════════════════════════════════════════════════
#  FASTAPI APP
# ═══════════════════════════════════════════════════════════════════════════

@asynccontextmanager
async def lifespan(app: FastAPI):
    # ── Startup ──────────────────────────────────────────────────────────
    logger.info("━" * 60)
    logger.info("  PYTHON AGENT SERVER  starting up")
    logger.info("━" * 60)

    ensure_directories()
    enforce_security_permissions()
    check_security_integrity()
    check_soul()

    logger.info("Provider health check:")
    await warmup_providers()

    logger.info("━" * 60)
    logger.info(f"  Server ready at http://{config.server.host}:{config.server.port}")
    logger.info(f"  API docs:       http://{config.server.host}:{config.server.port}/docs")
    logger.info(f"  WebSocket:      ws://{config.server.host}:{config.server.port}/ws/{{session_id}}")
    logger.info("━" * 60)

    yield  # application runs here

    # ── Shutdown ─────────────────────────────────────────────────────────
    logger.info("Agent server shutting down.")


app = FastAPI(
    title="Python Agent Server",
    description=(
        "Agentic orchestration server — provider-agnostic, parallel subagents, "
        "enterprise security, skills, and long-term memory."
    ),
    version="1.0.0",
    docs_url="/docs",
    redoc_url="/redoc",
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(router)
app.include_router(ws_router)

# ── Serve frontend ────────────────────────────────────────────────────────────
FRONTEND_DIR = Path(__file__).parent / "frontend"

@app.get("/", include_in_schema=False)
async def serve_frontend():
    return FileResponse(FRONTEND_DIR / "index.html")


# ═══════════════════════════════════════════════════════════════════════════
#  ENTRY POINT
# ═══════════════════════════════════════════════════════════════════════════

if __name__ == "__main__":
    uvicorn.run(
        "main:app",
        host=config.server.host,
        port=config.server.port,
        reload=config.server.reload,
        log_level="info",
    )
