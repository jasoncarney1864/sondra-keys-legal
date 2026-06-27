"""
Health check endpoints for monitoring application status.
"""

from __future__ import annotations

import asyncio
import logging
from datetime import datetime, timezone

import aiohttp
from azure.core.exceptions import AzureError
from azure.storage.blob.aio import ContainerClient
from fastapi import APIRouter, status
from fastapi.responses import JSONResponse
from sqlalchemy import text
from sqlalchemy.exc import SQLAlchemyError

from backend.app.core.config import settings
from backend.app.core.database import async_session_maker

router = APIRouter()
logger = logging.getLogger(__name__)

READINESS_TIMEOUT_SECONDS = 5


def _utc_timestamp() -> str:
    """Return a timezone-aware UTC timestamp."""
    return datetime.now(timezone.utc).isoformat()


async def _check_database() -> tuple[bool, str]:
    """Verify that the application can execute a simple SQL statement."""
    try:
        async with async_session_maker() as session:
            await session.execute(text("SELECT 1"))
        return True, "ok"
    except SQLAlchemyError as e:
        logger.warning("readiness_database_check_failed error=%s", e)
        return False, f"{type(e).__name__}: {str(e)[:200]}"
    except Exception as e:
        logger.warning("readiness_database_check_unexpected_error error=%s", e)
        return False, f"{type(e).__name__}: {str(e)[:200]}"


async def _check_search_index() -> tuple[bool, str]:
    """Verify Azure AI Search reachability and index existence."""
    stats_url = (
        "https://"
        f"{settings.azure.search_service_name}.search.windows.net/"
        f"indexes/{settings.azure.search_index_name}/stats?api-version=2023-11-01"
    )

    try:
        timeout = aiohttp.ClientTimeout(total=READINESS_TIMEOUT_SECONDS)
        async with aiohttp.ClientSession(timeout=timeout) as session:
            async with session.get(
                stats_url,
                headers={"api-key": settings.azure.search_api_key},
            ) as response:
                if response.status != 200:
                    body = (await response.text())[:200]
                    logger.warning(
                        "readiness_search_check_failed status=%s body=%s",
                        response.status,
                        body,
                    )
                    return False, f"status={response.status}: {body}"

                await response.json(content_type=None)

        return True, "ok"
    except Exception as e:
        logger.warning("readiness_search_check_unexpected_error error=%s", e)
        return False, f"{type(e).__name__}: {str(e)[:200]}"


async def _check_blob_container() -> tuple[bool, str]:
    """Verify Azure Blob Storage container reachability."""
    account_url = f"https://{settings.azure.blob_account_name}.blob.core.windows.net"
    container_client = ContainerClient(
        account_url=account_url,
        container_name=settings.azure.blob_container_name,
        credential=settings.azure.blob_account_key,
    )

    try:
        await container_client.get_container_properties()
        return True, "ok"
    except AzureError as e:
        logger.warning("readiness_blob_check_failed error=%s", e)
        return False, f"{type(e).__name__}: {str(e)[:200]}"
    except Exception as e:
        logger.warning("readiness_blob_check_unexpected_error error=%s", e)
        return False, f"{type(e).__name__}: {str(e)[:200]}"
    finally:
        await container_client.close()


@router.get("", status_code=status.HTTP_200_OK)
async def health_check():
    """
    Health check endpoint for load balancers and monitoring.
    
    Returns:
        Health status with timestamp
    """
    return {
        "status": "healthy",
        "timestamp": _utc_timestamp(),
    }


@router.get("/ready", status_code=status.HTTP_200_OK)
async def readiness_check():
    """
    Readiness check endpoint - indicates if service is ready for traffic.
    
    Returns:
        Readiness status
    """
    checks = await asyncio.gather(
        _check_database(),
        _check_search_index(),
        _check_blob_container(),
    )

    readiness = {
        "database": {"ready": checks[0][0], "detail": checks[0][1]},
        "search": {"ready": checks[1][0], "detail": checks[1][1]},
        "blob_storage": {"ready": checks[2][0], "detail": checks[2][1]},
    }

    is_ready = all(service["ready"] for service in readiness.values())
    payload = {
        "status": "ready" if is_ready else "not_ready",
        "timestamp": _utc_timestamp(),
        "checks": readiness,
    }

    if is_ready:
        return payload

    return JSONResponse(
        status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
        content=payload,
    )


@router.get("/live", status_code=status.HTTP_200_OK)
async def liveness_check():
    """
    Liveness check endpoint - indicates if service is running.
    
    Returns:
        Liveness status
    """
    return {
        "status": "alive",
        "timestamp": _utc_timestamp(),
    }
