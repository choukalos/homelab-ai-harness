FROM python:3.12-slim

WORKDIR /app

# Install Python dependencies from pyproject.toml
COPY pyproject.toml .
RUN pip install --no-cache-dir .

# yt-dlp (YouTube audio ingest for media_transcribe_song) — pip, pinned
# loosely (updates often). Pattern: mcp/servers/vision/Dockerfile.
RUN pip install --no-cache-dir yt-dlp

# Copy application code
COPY server.py .
COPY media_pipeline_client.py .

EXPOSE 8000

CMD ["python", "server.py"]