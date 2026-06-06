FROM python:3.12-slim

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

# Default: run the FastAPI web app
# Override with:
#   -- `celery -A core.celery_app.celery worker --loglevel=info`
#      to start a Celery worker instead
CMD ["uvicorn", "app:app", "--host", "0.0.0.0", "--port", "8090"]

