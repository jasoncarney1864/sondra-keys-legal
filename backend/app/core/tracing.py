"""Tracing bootstrap helpers."""

from __future__ import annotations

import os
from importlib.metadata import PackageNotFoundError, version

import structlog

from backend.app.core.config import settings

logger = structlog.get_logger(__name__)


def _openai_sdk_version() -> str | None:
    """Return installed OpenAI SDK version when available."""
    try:
        return version("openai")
    except PackageNotFoundError:
        return None


def _is_openai_sdk_compatible() -> tuple[bool, str | None]:
    """Check whether the installed OpenAI SDK exposes APIs required by the instrumentor."""
    try:
        from openai import NOT_GIVEN  # type: ignore

        _ = NOT_GIVEN
        return True, None
    except Exception as e:
        return False, f"{type(e).__name__}: {e}"


def configure_openai_instrumentation() -> None:
    """Enable OpenAI SDK instrumentation when available."""
    if not settings.tracing.enabled:
        logger.info("tracing_disabled")
        return

    if not settings.tracing.instrument_openai:
        logger.info("tracing_openai_instrumentation_disabled")
        return

    compatible, compatibility_error = _is_openai_sdk_compatible()
    if not compatible:
        logger.info(
            "tracing_openai_instrumentation_skipped_incompatible_openai_sdk",
            openai_sdk_version=_openai_sdk_version(),
            error=compatibility_error,
        )
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
