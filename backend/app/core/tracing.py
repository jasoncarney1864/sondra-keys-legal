"""Tracing bootstrap helpers."""

from __future__ import annotations

import os

import structlog

from backend.app.core.config import settings

logger = structlog.get_logger(__name__)


def configure_openai_instrumentation() -> None:
    """Enable OpenAI SDK instrumentation when available."""
    if not settings.tracing.enabled:
        logger.info("tracing_disabled")
        return

    if not settings.tracing.instrument_openai:
        logger.info("tracing_openai_instrumentation_disabled")
        return

    os.environ["OTEL_INSTRUMENTATION_GENAI_CAPTURE_MESSAGE_CONTENT"] = (
        "true" if settings.tracing.capture_message_content else "false"
    )

    try:
        from opentelemetry.instrumentation.openai_v2 import OpenAIInstrumentor

        OpenAIInstrumentor().instrument()
        logger.info(
            "tracing_openai_instrumentation_enabled",
            capture_message_content=settings.tracing.capture_message_content,
        )
    except Exception as e:
        # Tracing setup should never block app startup.
        logger.warning(
            "tracing_openai_instrumentation_failed",
            error=f"{type(e).__name__}: {e}",
        )
