"""
main.py  (Production v2)
------------------------
FastAPI server with:
  - API key authentication
  - Rate limiting (slowapi)
  - SQLite-backed conversation memory
  - MCP SSE endpoint for external MCP clients
  - Structured JSON logging
"""

from __future__ import annotations
import logging
import os
import traceback
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import Depends, FastAPI, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field
from slowapi import Limiter, _rate_limit_exceeded_handler
from slowapi.errors import RateLimitExceeded

import db
from auth import require_api_key
from config import get_settings
from agent_logic import run_agent
from doc_generator import generate_itinerary_doc

# ── Logging ───────────────────────────────────────────────────────────────────
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s — %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)
logger   = logging.getLogger(__name__)
settings = get_settings()

# ── Rate Limiter ──────────────────────────────────────────────────────────────
def _rate_key(request: Request) -> str:
    """Use API key as rate-limit bucket (falls back to IP)."""
    return request.headers.get("X-API-Key") or request.client.host

limiter = Limiter(key_func=_rate_key)

# ── Directories ───────────────────────────────────────────────────────────────
DOCS_DIR   = Path("generated_docs")
STATIC_DIR = Path("static")
DOCS_DIR.mkdir(exist_ok=True)
STATIC_DIR.mkdir(exist_ok=True)


# ── Lifespan ──────────────────────────────────────────────────────────────────
@asynccontextmanager
async def lifespan(app: FastAPI):
    db.init_db()
    logger.info("✅ Database ready at %s", settings.db_path)
    yield
    logger.info("Server shutting down.")


# ── App ───────────────────────────────────────────────────────────────────────
app = FastAPI(
    title=settings.app_name,
    description=(
        "Production-grade AI Travel Agent with real weather (Open-Meteo), "
        "real geocoding (Nominatim), real hotel names (OpenStreetMap), "
        "live currency rates (Frankfurter), and MCP tool protocol support."
    ),
    version="2.0.0",
    lifespan=lifespan,
)

app.state.limiter = limiter
app.add_exception_handler(RateLimitExceeded, _rate_limit_exceeded_handler)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

# ── Mount MCP SSE server (if mcp package installed) ───────────────────────────
try:
    from mcp_bridge import create_mcp_app
    from mcp.server.sse import SseServerTransport

    _mcp_instance = create_mcp_app()
    if _mcp_instance:
        _sse = SseServerTransport("/mcp/messages")

        @app.get("/mcp/sse")
        async def mcp_sse_endpoint(request: Request):
            """MCP SSE endpoint — connect external MCP clients here."""
            async with _sse.connect_sse(
                request.scope, request.receive, request._send
            ) as (r, w):
                await _mcp_instance._mcp_server.run(
                    r, w, _mcp_instance.initialization_options
                )

        @app.post("/mcp/messages")
        async def mcp_messages_endpoint(request: Request):
            return await _sse.handle_post_message(
                request.scope, request.receive, request._send
            )

        logger.info("✅ MCP SSE server mounted at /mcp/sse")
except Exception as e:
    logger.warning("MCP SSE server not mounted: %s", e)


# ── Schemas ───────────────────────────────────────────────────────────────────
class AgentRequest(BaseModel):
    user_id: str = Field(..., min_length=1, max_length=64, description="Unique user identifier.")
    query:   str = Field(..., min_length=5, max_length=2000, description="Travel planning request.")


class AgentResponse(BaseModel):
    user_id:      str
    query:        str
    itinerary:    dict
    doc_filename: str
    doc_url:      str
    message:      str


# ── Global error handler ──────────────────────────────────────────────────────
@app.exception_handler(Exception)
async def _global_error(request: Request, exc: Exception) -> JSONResponse:
    logger.error("Unhandled: %s\n%s", exc, traceback.format_exc())
    return JSONResponse(
        status_code=500,
        content={"detail": "Internal server error.", "error": str(exc)},
    )


@app.get("/ui", tags=["Frontend"])
async def root():
    """Serve the NeonTrip UI."""
    return FileResponse("static/index.html")


@app.get("/api-info", tags=["Health"])
async def api_info():
    return {
        "status":  "ok",
        "version": "2.0.0",
        "data_sources": {
            "weather":   "Open-Meteo (real-time, free)",
            "geocoding": "Nominatim / OpenStreetMap (free)",
            "hotels":    "OpenStreetMap Overpass (free)",
            "currency":  "Frankfurter / ECB (free)",
            "flights":   "Distance-based model with real coordinates",
        },
        "mcp_endpoint": "/mcp/sse",
        "ui":           "/ui",
    }


@app.get("/health", tags=["Health"])
async def health():
    return {"status": "healthy", "db": settings.db_path}


# ── Main Endpoint ─────────────────────────────────────────────────────────────
@app.post("/agent", response_model=AgentResponse, tags=["Travel Agent"])
@limiter.limit(f"{settings.rate_limit_per_minute}/minute")
async def agent_endpoint(
    request:  Request,
    body:     AgentRequest,
    _api_key: str = Depends(require_api_key),
):
    """
    Submit a travel planning query.
    Requires `X-API-Key` header.
    Rate limited to {rate_limit_per_minute} requests/minute per key.
    """
    logger.info("POST /agent user=%s query=%s", body.user_id, body.query[:80])
    try:
        itinerary = run_agent(user_id=body.user_id, query=body.query)

        doc_path     = generate_itinerary_doc(itinerary, body.user_id, str(DOCS_DIR))
        doc_filename = Path(doc_path).name
        base_url     = str(request.base_url).rstrip("/")

        return AgentResponse(
            user_id=body.user_id,
            query=body.query,
            itinerary=itinerary,
            doc_filename=doc_filename,
            doc_url=f"{base_url}/download/{doc_filename}",
            message="Itinerary generated with real live data.",
        )
    except RuntimeError as exc:
        raise HTTPException(status_code=500, detail=str(exc))
    except HTTPException:
        raise
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"Unexpected: {exc}")


# ── Download ──────────────────────────────────────────────────────────────────
@app.get("/download/{filename}", tags=["Documents"])
async def download_document(filename: str):
    safe = Path(filename).name
    fp   = DOCS_DIR / safe
    if not fp.exists():
        raise HTTPException(status_code=404, detail=f"'{safe}' not found.")
    return FileResponse(
        str(fp),
        media_type="application/vnd.openxmlformats-officedocument.wordprocessingml.document",
        filename=safe,
    )


@app.get("/docs-list", tags=["Documents"])
async def list_docs():
    docs = sorted([f.name for f in DOCS_DIR.glob("*.docx")], reverse=True)
    return {"count": len(docs), "documents": docs}


# ── Memory Management ─────────────────────────────────────────────────────────
@app.get("/memory/{user_id}", tags=["Memory"])
async def get_memory(user_id: str, _api_key: str = Depends(require_api_key)):
    """View conversation history for a user."""
    history = db.get_history(user_id)
    return {"user_id": user_id, "message_count": len(history), "history": history}


@app.delete("/memory/{user_id}", tags=["Memory"])
async def clear_memory(user_id: str, _api_key: str = Depends(require_api_key)):
    """Clear conversation history for a user."""
    deleted = db.clear_history(user_id)
    return {"status": "ok", "deleted_messages": deleted}


@app.get("/users", tags=["Memory"])
async def list_users(_api_key: str = Depends(require_api_key)):
    """List all users who have conversation history."""
    return {"users": db.list_users()}


# ── Static Files (mount LAST — catch-all) ────────────────────────────────────
app.mount("/static", StaticFiles(directory="static"), name="static")


# ── Entry Point ───────────────────────────────────────────────────────────────
if __name__ == "__main__":
    import uvicorn
    uvicorn.run("main:app", host="0.0.0.0", port=8000, reload=False)
