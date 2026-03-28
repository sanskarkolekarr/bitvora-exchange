FROM python:3.11-slim

WORKDIR /app

# Install dependencies first for layer caching
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy source code
COPY . .

# Expose internal port (never directly to public)
EXPOSE 8000

# Health check
HEALTHCHECK --interval=30s --timeout=10s --start-period=40s --retries=3 \
    CMD python -c "import httpx; httpx.get('http://localhost:8000/health').raise_for_status()"

# Run with uvicorn — production-tuned settings
# --workers 4: matches 4 vCPU, true parallelism
# --limit-concurrency 1000: max simultaneous connections per worker
# --backlog 2048: OS-level connection queue
# --timeout-keep-alive 5: close idle connections faster
CMD ["uvicorn", "app.main:app", \
     "--host", "0.0.0.0", \
     "--port", "8000", \
     "--workers", "4", \
     "--limit-concurrency", "1000", \
     "--backlog", "2048", \
     "--timeout-keep-alive", "5"]
