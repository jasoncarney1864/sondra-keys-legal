from uuid import UUID

import pytest

from backend.app.api.dependencies import get_query_service
from backend.app.core.config import settings
from backend.app.models.schemas import QueryResponse


@pytest.mark.asyncio
async def test_create_session_returns_user_scoped_session(client):
    response = await client.post(
        "/api/sessions",
        headers={"X-API-Key": settings.security.api_key},
    )

    assert response.status_code == 201
    payload = response.json()

    assert UUID(payload["session_id"])
    assert payload["user_id"] == settings.security.default_dev_user_id
    assert payload["active_document_id"] is None
    assert payload["expires_at"]


@pytest.mark.asyncio
async def test_query_rejects_when_no_document_ids_and_no_active_document(client, test_app):
    class StubQueryService:
        async def answer_query(self, request):
            return QueryResponse(
                question=request.question,
                answer="stub",
                citations=[],
                model_used="stub-model",
                latency_ms=0.1,
            )

    test_app.dependency_overrides[get_query_service] = lambda: StubQueryService()

    session_response = await client.post(
        "/api/sessions",
        headers={"X-API-Key": settings.security.api_key},
    )
    assert session_response.status_code == 201
    session_id = session_response.json()["session_id"]

    response = await client.post(
        "/api/query",
        headers={
            "X-API-Key": settings.security.api_key,
            "X-Session-Id": session_id,
        },
        json={
            "question": "What does this say?",
            "top_k": 5,
            "max_citations": 5,
        },
    )

    assert response.status_code == 400
    assert "No active document selected" in response.json()["detail"]


@pytest.mark.asyncio
async def test_delete_session_removes_sticky_context_and_allows_fresh_session(client):
    create_response = await client.post(
        "/api/sessions",
        headers={"X-API-Key": settings.security.api_key},
    )
    assert create_response.status_code == 201
    session_id = create_response.json()["session_id"]

    delete_response = await client.delete(
        f"/api/sessions/{session_id}",
        headers={"X-API-Key": settings.security.api_key},
    )
    assert delete_response.status_code == 204

    current_response = await client.get(
        "/api/sessions/current",
        headers={"X-API-Key": settings.security.api_key, "X-Session-Id": session_id},
    )
    assert current_response.status_code == 200
    payload = current_response.json()
    assert payload["session_id"] != session_id
    assert payload["active_document_id"] is None
