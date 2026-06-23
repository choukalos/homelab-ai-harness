#!/usr/bin/env bash
# DEPRECATED — see tests/channels/test_siri.sh
# This file is kept for backward compatibility. The canonical test lives in:
#   tests/channels/test_siri.sh
set -euo pipefail
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
bash "${SCRIPT_DIR}/channels/test_siri.sh"

