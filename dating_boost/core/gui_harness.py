"""Compatibility alias for the harness-owned native GUI implementation."""

import sys

from dating_boost.harness import native_gui as _implementation


sys.modules[__name__] = _implementation
