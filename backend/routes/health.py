"""
Health-check router — Stage 1.
Returns a simple OK payload so the frontend can verify wiring end-to-end.
"""
from fastapi import APIRouter
from pydantic import BaseModel

router = APIRouter()


class HealthResponse(BaseModel):
    status: str
    service: str
    version: str


@router.get("/health", response_model=HealthResponse, tags=["meta"])
async def health_check() -> HealthResponse:
    """Liveness probe — always returns 200 OK if the server is running."""
    return HealthResponse(
        status="ok",
        service="SignBridge AI",
        version="0.1.0",
    )
