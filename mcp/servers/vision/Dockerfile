FROM python:3.12-slim

WORKDIR /app

# System deps: ffmpeg/ffprobe (frame extraction) — not in the base image.
RUN apt-get update \
    && apt-get install -y --no-install-recommends ffmpeg \
    && rm -rf /var/lib/apt/lists/*

# Python dependencies from pyproject.toml
COPY pyproject.toml .
RUN pip install --no-cache-dir .

# yt-dlp (YouTube downloads) — pip, pinned loosely (updates often)
RUN pip install --no-cache-dir yt-dlp

# Copy application code
COPY server.py .

EXPOSE 8000

CMD ["python", "server.py"]