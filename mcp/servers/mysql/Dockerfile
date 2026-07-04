FROM python:3.12-slim

WORKDIR /app

# Install Python dependencies from pyproject.toml
COPY pyproject.toml .
RUN pip install --no-cache-dir .

# Copy application code
COPY server.py .

EXPOSE 8000

CMD ["python", "server.py"]
