# Backend Development Guide

## Project Structure

```
backend/
├── app/
│   ├── core/
│   │   └── config.py          # Pydantic settings & environment configuration
│   ├── services/
│   │   ├── document_processor.py  # Azure Content Understanding integration
│   │   ├── chunker.py            # Recursive text chunking strategy
│   │   └── qa_service.py         # Q&A generation using Azure OpenAI
│   ├── models/
│   │   ├── schemas.py            # Pydantic request/response models
│   │   └── database.py           # SQLAlchemy ORM models
│   ├── api/
│   │   ├── routes/
│   │   │   ├── documents.py      # Document upload/management endpoints
│   │   │   ├── qa.py             # Q&A endpoint
│   │   │   └── health.py         # Health check endpoint
│   │   └── dependencies.py       # Dependency injection
│   ├── main.py                 # FastAPI app initialization
│   └── __init__.py
├── tests/
│   ├── unit/
│   ├── integration/
│   └── conftest.py
├── requirements.txt
├── .env.example
├── Dockerfile
└── README.md (this file)
```

## Quick Start

### 1. Prerequisites

- Python 3.11+
- Azure subscription with:
  - Content Understanding API enabled
  - Cognitive Search instance
  - Blob Storage account
  - Azure OpenAI deployed
- Docker (for containerized deployment)

### 2. Local Development Setup

```bash
# Clone the repository
git clone <repo-url>
cd backend

# Create virtual environment
python -m venv venv

# Activate virtual environment
# On Windows:
venv\Scripts\activate
# On macOS/Linux:
source venv/bin/activate

# Install dependencies
pip install -r requirements.txt

# Copy and configure environment variables
cp .env.example .env
# Edit .env with your Azure credentials

# Run the application
uvicorn app.main:app --reload --host 0.0.0.0 --port 8000
```

### 3. API Endpoints

#### Health Check
```bash
GET /health
```

#### Upload Document
```bash
POST /api/documents/upload
Content-Type: multipart/form-data

file: <binary document data>
```

#### Ask Question
```bash
POST /api/qa/ask
Content-Type: application/json
Authorization: Bearer <API_KEY>

{
  "document_id": "uuid-of-document",
  "question": "What are the lease terms?"
}
```

## Core Components

### 1. Configuration (`core/config.py`)

Pydantic-based settings management with:
- **Azure Settings**: Content Understanding, Search, Blob Storage, OpenAI
- **Database Settings**: Connection strings and options
- **AI Settings**: Model configuration, chunking parameters
- **Security Settings**: API keys, CORS, file upload limits
- **Logging Settings**: Log levels and formats

**Key Features:**
- Environment variable loading from `.env` files
- Type validation through Pydantic
- Nested configuration classes for organization
- Support for multiple environments (dev, staging, prod)

### 2. Document Processor (`services/document_processor.py`)

Integrates with Azure Content Understanding API to:
- Extract text and metadata from documents
- Parse document structure (headings, sections)
- Handle multiple file formats (.pdf, .docx, .doc, .txt)
- Return structured extraction results

**Key Features:**
- Async HTTP client for API calls
- File type validation
- Structured output format
- Error handling and logging

### 3. Recursive Character Chunker (`services/chunker.py`)

Implements intelligent text chunking:
- Splits on semantic boundaries (paragraphs → sentences → words → characters)
- Maintains configurable overlap between chunks
- Preserves document structure
- Returns Chunk objects with metadata

**Key Features:**
- Customizable chunk size and overlap
- Multiple chunking strategies (basic and structure-aware)
- Position tracking for source location
- Dataclass-based chunk representation

## Configuration

### Environment Variables

Create a `.env` file from `.env.example`:

```bash
# Azure endpoints and credentials
AZURE_CONTENT_UNDERSTANDING_ENDPOINT=...
AZURE_CONTENT_UNDERSTANDING_KEY=...

# Database
DB_DATABASE_URL=sqlite:///./legal_qa.db

# AI/ML
AI_CHUNK_SIZE=1024
AI_CHUNK_OVERLAP=20

# Security
SECURITY_API_KEY=your-secure-key
```

### Azure Resources Required

1. **Document Intelligence (formerly Form Recognizer)**
   - Endpoint URL
   - API Key

2. **Cognitive Search**
   - Service name
   - API key
   - Index name

3. **Blob Storage**
   - Account name
   - Account key
   - Container name

4. **Azure OpenAI**
   - Endpoint URL
   - API key
   - Deployment name (e.g., "gpt-4")

### Azure OpenAI Deployment Setup

The application requires two Azure OpenAI **deployments** in your Azure OpenAI resource:

1. **Chat Completion Deployment** (for Q&A generation)
   - Create a deployment for a chat model (e.g., `gpt-4o`, `gpt-4`, `gpt-35-turbo`)
   - Set `AI_OPENAI_DEPLOYMENT_NAME` to match your deployment name exactly
   - Example: If you create a deployment called `gpt-4o-legal`, use:
     ```
     AI_OPENAI_DEPLOYMENT_NAME=gpt-4o-legal
     ```

2. **Embeddings Deployment** (for vector search)
   - Create a deployment for an embeddings model (e.g., `text-embedding-3-small`, `text-embedding-ada-002`)
   - Set `OPENAI_EMBEDDING_MODEL` to match your deployment name exactly
   - Example: If you create a deployment called `text-embedding-3-small`, use:
     ```
     OPENAI_EMBEDDING_MODEL=text-embedding-3-small
     ```

**Important Notes:**
- The deployment **name** in Azure OpenAI can differ from the model **type**
- You must create these deployments in your Azure OpenAI resource before starting the backend
- At startup, the backend will validate these deployments exist and log clear errors if missing
- Without valid deployments, queries will return fallback context-only responses

**To create deployments:**
1. Go to Azure Portal → Your Azure OpenAI resource → Model deployments
2. Click "Create new deployment"
3. Choose your model and give it a deployment name
4. Update your `.env` file with the exact deployment names

## Testing

### Run Unit Tests

```bash
pytest tests/unit -v
```

### Run Integration Tests

```bash
pytest tests/integration -v
```

### Run with Coverage

```bash
pytest tests/ --cov=app --cov-report=html
```

## Docker

### Build Image

```bash
docker build -t sondra-keys-backend:latest .
```

### Run Container

```bash
docker run -p 8000:8000 \
  --env-file .env \
  -v "$(pwd)/data:/workspace/data" \
  -e DB_DATABASE_URL="sqlite+aiosqlite:////workspace/data/legal_qa.db" \
  sondra-keys-backend:latest
```

For Windows PowerShell:

```powershell
docker run -p 8000:8000 `
  --env-file .env `
  -v "${PWD}\data:/workspace/data" `
  -e DB_DATABASE_URL="sqlite+aiosqlite:////workspace/data/legal_qa.db" `
  sondra-keys-backend:latest
```

## Deployment

### GitHub Actions CI/CD

The workflow automatically:
1. Builds and tests on every push
2. Builds Docker image for main branch
3. Deploys to Azure Container Apps
4. Runs health checks

**OIDC Authentication:**
- No long-lived credentials stored
- Uses Workload Identity Federation
- Requires GitHub Secrets:
  - `AZURE_CLIENT_ID`
  - `AZURE_TENANT_ID`
  - `AZURE_SUBSCRIPTION_ID`

### Manual Azure Deployment

```bash
# Deploy with Azure CLI
az containerapp up \
  --name sondra-keys-backend \
  --resource-group myResourceGroup \
  --image ghcr.io/yourorg/backend:latest

# Deploy infrastructure
az deployment group create \
  --resource-group myResourceGroup \
  --template-file infra/bicep/backend.bicep
```

## Development Workflow

### Code Quality

```bash
# Format code
black app/

# Sort imports
isort app/

# Run linter
flake8 app/

# Type checking
mypy app/
```

### Pre-commit Hooks

```bash
# Install pre-commit hooks
pre-commit install

# Run manually
pre-commit run --all-files
```

## Logging and Monitoring

### Application Logs

Structured JSON logging with OpenTelemetry:
```python
import logging
logger = logging.getLogger(__name__)
logger.info("event", extra={"key": "value"})
```

### Azure Application Insights

Configured via OpenTelemetry exporter for:
- Request tracing
- Performance monitoring
- Exception tracking
- Custom events

Runtime behavior:
- Backend auto-enables Azure Monitor when `APPLICATIONINSIGHTS_CONNECTION_STRING` is present.
- Startup logs `monitoring_configured_azure_monitor` on success.
- Monitoring init failures are non-fatal and logged as `monitoring_configuration_failed`.
- Ask pipeline emits step-level OpenTelemetry spans (`rag.answer_query`, `rag.embed_question`, `rag.retrieve_context`, `rag.call_llm`, `rag.build_citations`) for latency and outcome analysis.
- OpenAI SDK tracing auto-instruments at startup when `TRACING_ENABLED=true` and `TRACING_INSTRUMENT_OPENAI=true`.
- Query route adds hashed correlation attributes on request spans for filtering without exposing raw IDs:
  - `sondra.user.hash`
  - `sondra.session.hash`
  - `sondra.active_document.hash`
  - `sondra.scoped_document.hashes`
- If the installed OpenAI SDK is incompatible with the OpenTelemetry OpenAI instrumentor, startup logs `tracing_openai_instrumentation_skipped_incompatible_openai_sdk` and continues without failing.

Tracing toggles:
- `TRACING_ENABLED` (default `true`): enables tracing bootstrap.
- `TRACING_INSTRUMENT_OPENAI` (default `true`): enables OpenAI SDK instrumentation.
- `TRACING_CAPTURE_MESSAGE_CONTENT` (default `false`): includes prompt/completion content in telemetry logs.

## Troubleshooting

### Authentication Issues

- Verify Azure credentials in `.env`
- Check API keys and endpoints
- Validate subscription and resource group

### Document Processing Errors

- Ensure file format is supported
- Check file size doesn't exceed limit
- Verify Azure Content Understanding service is accessible

### Chunking Problems

- Adjust `CHUNK_SIZE` and `CHUNK_OVERLAP` parameters
- Verify text extraction succeeded
- Check available memory for large documents

## Next Steps

1. Implement `app/services/qa_service.py` for Q&A generation
2. Create database models in `app/models/database.py`
3. Implement API routes in `app/api/routes/`
4. Add comprehensive test coverage
5. Set up infrastructure as code (Bicep templates)
