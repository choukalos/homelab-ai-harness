#!/usr/bin/env bash
# One-time MySQL provisioning for data-hub / report-hub.
# Renders the provisioning SQL from homelab/.env (DH_APP_PASS /
# DH_REPORTS_PASS) and pipes it to `sudo mysql`. Idempotent — safe to
# re-run. The rendered SQL is intentionally NOT committed (see .gitignore).
set -euo pipefail

HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ENV_FILE="$HERE/../.env"
[[ -f "$ENV_FILE" ]] || { echo "missing $ENV_FILE" >&2; exit 1; }

source <(grep -E '^(DH_APP_USER|DH_APP_PASS|DH_REPORTS_USER|DH_REPORTS_PASS)=' "$ENV_FILE")
[[ -n "${DH_APP_PASS:-}" && -n "${DH_REPORTS_PASS:-}" ]] || {
  echo "DH_APP_PASS / DH_REPORTS_PASS missing from $ENV_FILE" >&2; exit 1;
}

cat <<SQL | sudo mysql
-- data-hub / report-hub provisioning (rendered from homelab/.env)
CREATE DATABASE IF NOT EXISTS finance  CHARACTER SET utf8mb4 COLLATE utf8mb4_0900_ai_ci;
CREATE DATABASE IF NOT EXISTS reports  CHARACTER SET utf8mb4 COLLATE utf8mb4_0900_ai_ci;
CREATE DATABASE IF NOT EXISTS hub      CHARACTER SET utf8mb4 COLLATE utf8mb4_0900_ai_ci;

CREATE USER IF NOT EXISTS '${DH_APP_USER}'@'%'         IDENTIFIED BY '${DH_APP_PASS}';
CREATE USER IF NOT EXISTS '${DH_APP_USER}'@'localhost' IDENTIFIED BY '${DH_APP_PASS}';
CREATE USER IF NOT EXISTS '${DH_REPORTS_USER}'@'%'         IDENTIFIED BY '${DH_REPORTS_PASS}';
CREATE USER IF NOT EXISTS '${DH_REPORTS_USER}'@'localhost' IDENTIFIED BY '${DH_REPORTS_PASS}';

GRANT ALL PRIVILEGES ON finance.* TO '${DH_APP_USER}'@'%';
GRANT ALL PRIVILEGES ON finance.* TO '${DH_APP_USER}'@'localhost';
GRANT SELECT ON finance.* TO '${DH_REPORTS_USER}'@'%';
GRANT SELECT ON finance.* TO '${DH_REPORTS_USER}'@'localhost';
GRANT ALL PRIVILEGES ON reports.* TO '${DH_REPORTS_USER}'@'%';
GRANT ALL PRIVILEGES ON reports.* TO '${DH_REPORTS_USER}'@'localhost';

-- v2: generic datasets (hub db): dh_app writes, dh_reports + ai read
GRANT ALL PRIVILEGES ON hub.* TO '${DH_APP_USER}'@'%';
GRANT ALL PRIVILEGES ON hub.* TO '${DH_APP_USER}'@'localhost';
GRANT SELECT ON hub.* TO '${DH_REPORTS_USER}'@'%';
GRANT SELECT ON hub.* TO '${DH_REPORTS_USER}'@'localhost';
GRANT SELECT ON hub.* TO 'ai'@'%';

-- existing AI read-only user: finance access for mcp_mysql Q&A
GRANT SELECT ON finance.* TO 'ai'@'%';

FLUSH PRIVILEGES;
SQL

echo "provisioned: finance + reports + hub DBs; ${DH_APP_USER} (finance/hub writer); ${DH_REPORTS_USER} (reports owner, finance+hub read-only); ai SELECT on finance+hub"