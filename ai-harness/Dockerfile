FROM python:3.12-slim

# Kaleido needs Chromium to render PNG/SVG images
RUN apt-get update && \
    apt-get install -y --no-install-recommends chromium && \
    rm -rf /var/lib/apt/lists/*

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

# Default: run the FastAPI web app
# Override with:
#   -- `celery -A infra.core.celery_app.celery worker --loglevel=info`
#      to start a Celery worker instead
CMD ["uvicorn", "app:app", "--host", "0.0.0.0", "--port", "8090"]

