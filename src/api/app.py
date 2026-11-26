"""FastAPI Gateway Application with CORS, routing, static serving, and health checks."""

import logging
from pathlib import Path
from typing import Optional

from fastapi import FastAPI, Header, HTTPException, Request, status
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles

from src.api.routes import audit, product, support
from src.config import Settings, get_settings

logger = logging.getLogger(__name__)

settings = get_settings()

app = FastAPI(
    title="Human-in-the-Loop AI Assistant Gateway",
    version="1.0.0",
    description="Role-specific HITL API Gateway for Support Specialists, Product Managers, and Compliance Auditors.",
)

# ------------------------------------------------------------------------------
# CORS Middleware
# ------------------------------------------------------------------------------
origins = settings.CORS_ORIGINS or ["*"]
# If wildcard is in origins or specific Railway/Vercel domains
app.add_middleware(
    CORSMiddleware,
    allow_origins=origins if "*" not in origins else ["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


# ------------------------------------------------------------------------------
# Security Dependency
# ------------------------------------------------------------------------------
def verify_api_key(
    x_api_key: Optional[str] = Header(None, alias="X-API-Key"),
    authorization: Optional[str] = Header(None),
) -> Optional[str]:
    """Validate API key if supplied in headers."""
    provided_key = x_api_key
    if not provided_key and authorization and authorization.startswith("Bearer "):
        provided_key = authorization.replace("Bearer ", "").strip()

    expected_key = settings.SUPPORT_API_KEY
    if provided_key:
        if provided_key != expected_key:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Invalid API key provided.",
            )
        return provided_key
    return None


# ------------------------------------------------------------------------------
# API Routers
# ------------------------------------------------------------------------------
app.include_router(support.router, prefix="/api")
app.include_router(product.router, prefix="/api")
app.include_router(audit.router, prefix="/api")


@app.get("/api/health")
def health_check():
    """Health check endpoint confirming API gateway operational status."""
    return {
        "status": "healthy",
        "service": "hitl-ai-assistant",
        "environment": settings.ENVIRONMENT,
        "version": "1.0.0",
        "cors_origins": settings.CORS_ORIGINS,
    }


# ------------------------------------------------------------------------------
# Static UI Mounting & Root Index Handler
# ------------------------------------------------------------------------------
workspace_root = Path(__file__).resolve().parent.parent.parent
static_dir = workspace_root / "static"
if not static_dir.exists():
    static_dir = Path(__file__).resolve().parent / "static"

if static_dir.exists():
    app.mount("/static", StaticFiles(directory=str(static_dir)), name="static")


@app.get("/")
def serve_index():
    """Serve the single-page application frontend."""
    index_file = static_dir / "index.html"
    if index_file.exists():
        return FileResponse(str(index_file))
    return JSONResponse(
        content={
            "message": "Human-in-the-Loop Gateway API online.",
            "docs": "/docs",
            "health": "/api/health",
        },
        status_code=200,
    )
