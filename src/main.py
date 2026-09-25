import os

from dotenv import load_dotenv
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

from src.api.routes import router

load_dotenv()

app = FastAPI(
    title="AI Code Review & PR Assistant",
    description="Automated code review and pull-request analysis powered by LLMs.",
    version="0.1.0",
)

# ---------------------------------------------------------------------------
# CORS
# ---------------------------------------------------------------------------
allowed_origins = os.getenv("ALLOWED_ORIGINS", "*").split(",")

app.add_middleware(
    CORSMiddleware,
    allow_origins=allowed_origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# ---------------------------------------------------------------------------
# Routers
# ---------------------------------------------------------------------------
app.include_router(router, prefix="/api")


# ---------------------------------------------------------------------------
# Health check
# ---------------------------------------------------------------------------
@app.get("/health", tags=["Health"])
async def health_check() -> dict:
    """Returns service liveness status."""
    return {"status": "ok", "service": "ai-code-review-assistant"}


# ---------------------------------------------------------------------------
# Static files — mount last so API routes take priority
# ---------------------------------------------------------------------------
_STATIC_DIR = os.path.join(os.path.dirname(__file__), "static")

app.mount("/", StaticFiles(directory=_STATIC_DIR, html=True), name="static")
