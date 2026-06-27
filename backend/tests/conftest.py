import os
from collections.abc import AsyncGenerator

import pytest_asyncio
from httpx import ASGITransport, AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine


def _set_test_env_defaults() -> None:
    defaults = {
        "AZURE_CONTENT_UNDERSTANDING_ENDPOINT": "https://example.cognitiveservices.azure.com",
        "AZURE_CONTENT_UNDERSTANDING_KEY": "test-key",
        "AZURE_SEARCH_SERVICE_NAME": "test-search",
        "AZURE_SEARCH_API_KEY": "test-search-key",
        "AZURE_BLOB_ACCOUNT_NAME": "testblob",
        "AZURE_BLOB_ACCOUNT_KEY": "test-blob-key",
        "AI_OPENAI_API_KEY": "test-ai-openai-key",
        "AI_OPENAI_ENDPOINT": "https://example.openai.azure.com",
        "AI_OPENAI_DEPLOYMENT_NAME": "gpt-4o",
        "OPENAI_API_KEY": "test-openai-key",
        "SECURITY_API_KEY": "test-api-key",
        "DB_DATABASE_URL": "sqlite+aiosqlite:///./test-app-import.db",
        "STARTUP_INDEX_SANITY_CHECK_ENABLED": "false",
        "USER_SESSION_RETENTION_CLEANUP_ENABLED": "false",
        "PARSED_JSON_RETENTION_CLEANUP_ENABLED": "false",
    }
    for key, value in defaults.items():
        os.environ.setdefault(key, value)


_set_test_env_defaults()

from backend.app.api.dependencies import get_db_session  # noqa: E402
from backend.app.main import app  # noqa: E402
from backend.app.models.db import Base  # noqa: E402


@pytest_asyncio.fixture
async def db_session_maker(tmp_path) -> AsyncGenerator[async_sessionmaker[AsyncSession], None]:
    db_path = tmp_path / "integration.db"
    db_url = f"sqlite+aiosqlite:///{db_path.as_posix()}"

    engine = create_async_engine(db_url)
    maker = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)

    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    try:
        yield maker
    finally:
        await engine.dispose()


@pytest_asyncio.fixture
async def test_app(db_session_maker) -> AsyncGenerator:
    async def _override_get_db_session() -> AsyncGenerator[AsyncSession, None]:
        async with db_session_maker() as session:
            yield session

    app.dependency_overrides[get_db_session] = _override_get_db_session
    try:
        yield app
    finally:
        app.dependency_overrides.clear()


@pytest_asyncio.fixture
async def client(test_app) -> AsyncGenerator[AsyncClient, None]:
    transport = ASGITransport(app=test_app)
    async with AsyncClient(transport=transport, base_url="http://localhost") as async_client:
        yield async_client
