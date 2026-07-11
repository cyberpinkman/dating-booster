"""Compatibility alias for the TaShuo-owned stage alpha evidence checks."""

import sys

from dating_boost.apps.tashuo import stage_alpha_evidence as _implementation


sys.modules[__name__] = _implementation
