#!/usr/bin/env bash
set -euo pipefail

INSTALLER_REF="${DATING_BOOST_INSTALL_REF:-main}"
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" >/dev/null 2>&1 && pwd)"
COMMON_LOCAL="$SCRIPT_DIR/lib/install-agent-common.sh"
if [ -f "$COMMON_LOCAL" ]; then
  # shellcheck source=lib/install-agent-common.sh
  . "$COMMON_LOCAL"
else
  COMMON_TMP="$(mktemp)"
  curl -fsSL "https://raw.githubusercontent.com/cyberpinkman/dating-booster/${INSTALLER_REF}/scripts/lib/install-agent-common.sh" -o "$COMMON_TMP"
  # shellcheck source=/dev/null
  . "$COMMON_TMP"
fi

dating_boost_install_cli
dating_boost_cli adapter codex install --scope "$DATING_BOOST_INSTALL_SCOPE" --json
dating_boost_cli adapter codex doctor --data-dir "$DATING_BOOST_DATA_DIR" --json
dating_boost_warn_if_script_not_on_path
