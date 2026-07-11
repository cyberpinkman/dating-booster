"""Compatibility alias for the TaShuo-owned standalone alpha gate."""

import sys

from dating_boost.apps.tashuo import standalone_alpha_gate as _implementation


sys.modules[__name__] = _implementation
