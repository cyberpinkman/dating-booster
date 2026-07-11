"""Compatibility alias for the TaShuo-owned stage alpha utilities."""

import sys

from dating_boost.apps.tashuo import stage_alpha_utils as _implementation


sys.modules[__name__] = _implementation
