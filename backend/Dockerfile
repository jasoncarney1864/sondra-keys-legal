# --- Stage 1: Build & Dependency Installation ---
FROM python:3.11-slim AS builder

WORKDIR /build

# Install build dependencies
RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential \
    python3-dev \
    && rm -rf /var/lib/apt/lists/*

# Copy requirements and install Python dependencies
COPY requirements.txt .
RUN pip install --user --no-cache-dir -r requirements.txt

# --- Stage 2: Final Secure Runtime ---
FROM python:3.11-slim

# Use a generic workspace root
WORKDIR /workspace

# Install runtime dependencies (keeping curl for the healthcheck)
RUN apt-get update && apt-get install -y --no-install-recommends \
    curl \
    && rm -rf /var/lib/apt/lists/*

# Create a secure non-root system user
RUN groupadd -g 10001 appuser && \
    useradd -u 10001 -g appuser -s /sbin/nologin -c "Docker image user" appuser

# Copy Python dependencies from builder to the secure user's home directory
COPY --from=builder /root/.local /home/appuser/.local

# Set environment variables mapping the binary path and registering the PYTHONPATH
ENV PATH=/home/appuser/.local/bin:$PATH \
    PYTHONPATH=/workspace \
    PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1

# Copy application code into the expected 'backend/app' nesting structure
COPY --chown=appuser:appuser app/ ./backend/app/

# Switch to the secure non-root user
USER appuser

# Container level health check
HEALTHCHECK --interval=30s --timeout=10s --start-period=5s --retries=3 \
    CMD curl -f http://localhost:8000/health || exit 1

# Expose port
EXPOSE 8000

# Run application pointing to the updated absolute path spec
CMD ["uvicorn", "backend.app.main:app", "--host", "0.0.0.0", "--port", "8000", "--workers", "4"]