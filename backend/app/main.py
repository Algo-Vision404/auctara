from __future__ import annotations

import logging

from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from app.api.routes import agents, audit, dashboard, health, policies, tasks, transactions
from app.config import get_settings
from app.database.migrations import run_migrations

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("agentauth")


@asynccontextmanager
async def lifespan(app: FastAPI):
    run_migrations()
    s = get_settings()
    logger.info("AgentAuth backend started. PayPal env=%s, model=%s", s.paypal_environment, s.openrouter_model)
    yield


app = FastAPI(title="AgentAuth API", version="1.0.0", lifespan=lifespan)

settings = get_settings()
allowed_origins = {settings.frontend_url, "http://localhost:3000", "http://127.0.0.1:3000"}
app.add_middleware(
    CORSMiddleware,
    allow_origins=list(allowed_origins),
    allow_origin_regex=r"https://.*\.e2b\.app",
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.exception_handler(Exception)
async def unhandled_exception_handler(request: Request, exc: Exception):
    logger.exception("Unhandled error on %s", request.url)
    return JSONResponse(status_code=500, content={"detail": f"Internal error: {exc}"})


app.include_router(health.router, tags=["health"])
app.include_router(agents.router, tags=["agents"])
app.include_router(tasks.router, tags=["tasks"])
app.include_router(transactions.router, tags=["transactions"])
app.include_router(policies.router, tags=["policies"])
app.include_router(audit.router, tags=["audit"])
app.include_router(dashboard.router, tags=["dashboard"])


@app.get("/")
def root():
    return {"name": "AgentAuth API", "status": "running"}
