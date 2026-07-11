"""Compatibility alias for the TaShuo-owned stage alpha safety checks."""

import sys

from dating_boost.apps.tashuo import stage_alpha_safety as _implementation


sys.modules[__name__] = _implementation
