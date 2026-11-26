# Multi-stage Dockerfile for Human-in-the-Loop (HITL) Support & Product Intelligence System
FROM python:3.11-slim as base

# Set environment variables
ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PIP_NO_CACHE_DIR=1 \
    PORT=8000

# Install system dependencies
RUN apt-get update && apt-get install -y --no-install-recommends \
    curl \
    build-essential \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

# Copy dependency manifest and install requirements
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Pre-cache SentenceTransformer model to guarantee zero runtime network dependency
RUN python -c "from sentence_transformers import SentenceTransformer; SentenceTransformer('all-MiniLM-L6-v2')"

# Copy application source, data, static assets, scripts, and configuration
COPY src/ ./src/
COPY data/ ./data/
COPY static/ ./static/
COPY scripts/ ./scripts/
COPY pyproject.toml .
COPY .env.example .env

# Create persistence directories
RUN mkdir -p data/audit data/explainers data/corpus

# Expose backend port
EXPOSE 8000

# Docker healthcheck querying /api/health
HEALTHCHECK --interval=30s --timeout=5s --start-period=30s --retries=3 \
    CMD curl -f http://localhost:${PORT:-8000}/api/health || exit 1

# Launch production server with Uvicorn dynamically binding to $PORT
CMD ["sh", "-c", "uvicorn src.api.app:app --host 0.0.0.0 --port ${PORT:-8000}"]
