FROM python:3.12-slim

WORKDIR /app

# WeasyPrint system deps (pango/cairo stack) for media_render_tab_pdf +
# poppler-utils for PDF QA (pdffonts / pdftotext).
RUN apt-get update && apt-get install -y --no-install-recommends \
      libpango-1.0-0 libpangocairo-1.0-0 libpangoft2-1.0-0 \
      libharfbuzz-subset0 libffi8 shared-mime-info fontconfig \
      fonts-dejavu-core poppler-utils \
    && rm -rf /var/lib/apt/lists/*

# Install Python dependencies from pyproject.toml
COPY pyproject.toml .
RUN pip install --no-cache-dir .

# yt-dlp (YouTube audio ingest for media_transcribe_song) — pip, pinned
# loosely (updates often). Pattern: mcp/servers/vision/Dockerfile.
RUN pip install --no-cache-dir yt-dlp

# WeasyPrint (media_render_tab_pdf — PDF song sheets)
RUN pip install --no-cache-dir weasyprint

# Song-sheet fonts (variable TTFs from google/fonts; best-effort —
# fonts-dejavu-core is the fallback if the CDN is unreachable at build time).
# NOTE: WeasyPrint 70 resolves fonts via Pango/fontconfig and its @font-face
# path cannot instantiate the JetBrains Mono variable font — the generator's
# CSS uses fontconfig family names, so these just need to be installed.
RUN python - <<'EOF'
import os, urllib.request
os.makedirs("/usr/share/fonts/tabpdf", exist_ok=True)
fonts = {
    "PlayfairDisplay.ttf":
        "https://github.com/google/fonts/raw/main/ofl/playfairdisplay/PlayfairDisplay%5Bwght%5D.ttf",
    "Lora-Italic.ttf":
        "https://github.com/google/fonts/raw/main/ofl/lora/Lora-Italic%5Bwght%5D.ttf",
    "Inter.ttf":
        "https://github.com/google/fonts/raw/main/ofl/inter/Inter%5Bopsz%2Cwght%5D.ttf",
    "JetBrainsMono.ttf":
        "https://github.com/google/fonts/raw/main/ofl/jetbrainsmono/JetBrainsMono%5Bwght%5D.ttf",
}
for name, url in fonts.items():
    try:
        urllib.request.urlretrieve(url, f"/usr/share/fonts/tabpdf/{name}")
        print("font ok:", name)
    except Exception as e:
        print("font skip:", name, e)
EOF
RUN fc-cache -f

# Copy application code
COPY server.py .
COPY media_pipeline_client.py .
COPY tab_pdf.py .

EXPOSE 8000

CMD ["python", "server.py"]