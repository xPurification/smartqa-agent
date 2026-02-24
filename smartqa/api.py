"""FastAPI service layer exposing /analyze, /run-tests, and /health endpoints."""

from __future__ import annotations

from contextlib import asynccontextmanager
from typing import AsyncIterator

from fastapi import FastAPI, HTTPException

from smartqa import __version__
from smartqa.agent import SmartQAAgent
from smartqa.config import get_settings
from smartqa.logging_config import get_logger, setup_logging
from smartqa.models import (
    AnalyzeRequest,
    HealthResponse,
    QAReport,
    RunTestsRequest,
    TestPlan,
)

logger = get_logger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    settings = get_settings()
    setup_logging(settings.log_level)
    logger.info("SmartQA API starting (v%s)", __version__)
    yield
    logger.info("SmartQA API shutting down")


app = FastAPI(
    title="SmartQA Agent API",
    description="AI-powered autonomous test automation service",
    version=__version__,
    lifespan=lifespan,
)


def _build_agent() -> SmartQAAgent:
    settings = get_settings()
    if not settings.claude_api_key:
        raise HTTPException(
            status_code=500,
            detail="CLAUDE_API_KEY is not configured",
        )
    return SmartQAAgent(settings=settings)


@app.get("/health", response_model=HealthResponse)
async def health() -> HealthResponse:
    return HealthResponse(status="healthy", version=__version__)


@app.post("/analyze", response_model=TestPlan)
async def analyze(request: AnalyzeRequest) -> TestPlan:
    """Analyze a URL and return a generated test plan."""
    logger.info("POST /analyze — url=%s", request.url)
    try:
        agent = _build_agent()
        return agent.analyze(request.url)
    except HTTPException:
        raise
    except Exception as exc:
        logger.exception("Analysis failed for %s", request.url)
        raise HTTPException(status_code=500, detail=str(exc)) from exc


@app.post("/run-tests", response_model=QAReport)
async def run_tests(request: RunTestsRequest) -> QAReport:
    """Run the full test pipeline against a URL and return a QA report."""
    logger.info("POST /run-tests — url=%s", request.url)
    try:
        agent = _build_agent()
        return agent.run(request.url)
    except HTTPException:
        raise
    except Exception as exc:
        logger.exception("Test run failed for %s", request.url)
        raise HTTPException(status_code=500, detail=str(exc)) from exc
