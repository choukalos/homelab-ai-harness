#!/usr/bin/env bash
# DEPRECATED — see tests/smoke/test_creative.sh
# This file is kept for backward compatibility. The canonical test lives in:
#   tests/smoke/test_creative.sh
set -uo pipefail
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
bash "${SCRIPT_DIR}/smoke/test_creative.sh"
