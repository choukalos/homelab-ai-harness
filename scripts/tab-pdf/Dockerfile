# tab-pdf — render a transcribed song (tab.md + analysis.json + lyrics.txt)
# into a visually appealing PDF song sheet.
#
# The generator's CANONICAL source is mcp/servers/media/tab_pdf.py (also
# used in-process by the mcp_media `media_render_tab_pdf` tool). This image
# is a standalone/QA wrapper around it (poppler-utils for pdffonts/pdftotext).
#
# Build (from the REPO ROOT — the generator lives in mcp/servers/media/):
#   docker build -t homelab-tab-pdf:local -f scripts/tab-pdf/Dockerfile .
#
# Run:
#   docker run --rm -v /home/chuck/data/media/generated/pipeline:/work \
#     homelab-tab-pdf:local riptide -o /work/riptide/riptide-tab.pdf \
#     --title "Riptide" --artist "Vance Joy"
#
# The generator is deterministic — no LLM involved.

FROM python:3.12-slim

# WeasyPrint system deps (pango/cairo stack) + poppler-utils for QA rendering.
RUN apt-get update && apt-get install -y --no-install-recommends \
      libpango-1.0-0 libpangocairo-1.0-0 libpangoft2-1.0-0 \
      libharfbuzz-subset0 libffi8 shared-mime-info fontconfig \
      fonts-dejavu-core poppler-utils \
    && rm -rf /var/lib/apt/lists/*

RUN pip install --no-cache-dir weasyprint

# Fonts (variable TTFs from google/fonts; best-effort — DejaVu fallback if
# the CDN is unreachable at build time).
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

# Canonical generator (shared with the mcp_media container).
COPY mcp/servers/media/tab_pdf.py /app/tab_pdf.py
WORKDIR /work
ENTRYPOINT ["python", "/app/tab_pdf.py"]