#!/usr/bin/env bash
set -euo pipefail

DATING_BOOST_INSTALL_REF="${DATING_BOOST_INSTALL_REF:-main}"
DATING_BOOST_PACKAGE_SPEC="${DATING_BOOST_PACKAGE_SPEC:-git+https://github.com/cyberpinkman/dating-booster.git@${DATING_BOOST_INSTALL_REF}}"
DATING_BOOST_INSTALL_SCOPE="${DATING_BOOST_INSTALL_SCOPE:-user}"
DATING_BOOST_DATA_DIR="${DATING_BOOST_DATA_DIR:-$HOME/.dating-boost}"
DATING_BOOST_PYTHON="${DATING_BOOST_PYTHON:-python3}"

dating_boost_require_python() {
  "$DATING_BOOST_PYTHON" - <<'PY'
import sys
if sys.version_info < (3, 11):
    raise SystemExit("Dating Booster requires Python >= 3.11")
PY
}

dating_boost_ensure_pip() {
  if "$DATING_BOOST_PYTHON" -m pip --version >/dev/null 2>&1; then
    return 0
  fi
  "$DATING_BOOST_PYTHON" -m ensurepip --upgrade >/dev/null
}

dating_boost_install_cli() {
  dating_boost_require_python
  dating_boost_ensure_pip
  "$DATING_BOOST_PYTHON" -m pip install --user --upgrade "$DATING_BOOST_PACKAGE_SPEC"
}

dating_boost_cli() {
  "$DATING_BOOST_PYTHON" -m dating_boost.cli "$@"
}

dating_boost_warn_if_script_not_on_path() {
  if command -v dating-boost >/dev/null 2>&1; then
    return 0
  fi
  cat >&2 <<'TXT'
Warning: dating-boost is not on PATH. The installed skill can still use
python3 -m dating_boost.cli, but adding your Python user scripts directory to
PATH is recommended.
TXT
}
