# =============================================================================
# Mektep Platform - Simplified Dockerfile
# =============================================================================
# Lightweight image for auth, API, and admin panel
# Scraping/browser automation moved to desktop app
# =============================================================================

FROM python:3.13-slim as builder

WORKDIR /app

# Install build dependencies
RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential \
    libpq-dev \
    && rm -rf /var/lib/apt/lists/*

# Install Python dependencies
COPY requirements.txt .
RUN pip install --no-cache-dir --user -r requirements.txt

# =============================================================================
# Production image
# =============================================================================
FROM python:3.13-slim

WORKDIR /app

# Install runtime dependencies (PostgreSQL client only)
RUN apt-get update && apt-get install -y --no-install-recommends \
    libpq5 \
    && rm -rf /var/lib/apt/lists/*

# Copy installed packages from builder
COPY --from=builder /root/.local /root/.local
ENV PATH=/root/.local/bin:$PATH

# Copy application
COPY . .

# Create data directories
RUN mkdir -p /app/data/uploads /app/instance

# Default environment
ENV FLASK_ENV=production
ENV PYTHONUNBUFFERED=1

# Expose port
EXPOSE 5000

# Health check
HEALTHCHECK --interval=30s --timeout=10s --start-period=5s --retries=3 \
    CMD python -c "import urllib.request; urllib.request.urlopen('http://localhost:5000/health')" || exit 1

# Run with Waitress (works on all platforms)
CMD ["python", "run_production.py"]
