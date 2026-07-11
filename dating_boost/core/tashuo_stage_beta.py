"""Compatibility alias for the TaShuo-owned stage beta implementation."""

import sys

from dating_boost.apps.tashuo import stage_beta as _implementation


sys.modules[__name__] = _implementation
