"""Compatibility alias for the TaShuo-owned stage alpha release gate."""

import sys

from dating_boost.apps.tashuo import stage_alpha_release_gate as _implementation


sys.modules[__name__] = _implementation
