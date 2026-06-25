"""
Health check endpoints for monitoring application status.
"""

from fastapi import APIRouter, status
from datetime import datetime

router = APIRouter()


@router.get("", status_code=status.HTTP_200_OK)
async def health_check():
    """
    Health check endpoint for load balancers and monitoring.
    
    Returns:
        Health status with timestamp
    """
    return {
        "status": "healthy",
        "timestamp": datetime.utcnow().isoformat(),
    }


@router.get("/ready", status_code=status.HTTP_200_OK)
async def readiness_check():
    """
    Readiness check endpoint - indicates if service is ready for traffic.
    
    In a production system, this would check:
    - Database connectivity
    - Azure service connectivity
    - Cache availability
    
    Returns:
        Readiness status
    """
    return {
        "status": "ready",
        "timestamp": datetime.utcnow().isoformat(),
    }


@router.get("/live", status_code=status.HTTP_200_OK)
async def liveness_check():
    """
    Liveness check endpoint - indicates if service is running.
    
    Returns:
        Liveness status
    """
    return {
        "status": "alive",
        "timestamp": datetime.utcnow().isoformat(),
    }
