# CHOUKALOS // HOMELAB — public portal server.
# Stdlib-only Python: no pip installs, no supply chain beyond the base image.
# See portal/server.py docstring for routes and security properties.
FROM python:3.12-slim

COPY server.py /app/server.py

# Run as uid 1000 (matches host owner chuck:chuck — all mounted dirs are
# owned by 1000 and world-readable). No user entry needed.
USER 1000:1000

EXPOSE 8080

# Liveness healthcheck is defined in compose/compose.portal.yml (needs a
# multi-line script; `/` always answers 200 when a deploy is present and
# 503 while syncing — both mean the server is up).

CMD ["python3", "/app/server.py"]