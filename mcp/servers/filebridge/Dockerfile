FROM python:3.12-slim

WORKDIR /app

# Install Python dependencies from pyproject.toml
COPY pyproject.toml .
RUN pip install --no-cache-dir .

# Copy application code + policy config
COPY app.py .
COPY filebridge.yaml .

EXPOSE 8000

# python:3.12-slim has no curl — healthcheck via urllib.
HEALTHCHECK --interval=30s --timeout=5s --start-period=10s --retries=3 \
  CMD python -c "import urllib.request,sys; sys.exit(0 if urllib.request.urlopen('http://127.0.0.1:8000/health', timeout=4).status == 200 else 1)"

CMD ["python", "app.py"]
