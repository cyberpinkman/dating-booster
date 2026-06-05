"""App adapter registry for supported dating/chat applications."""

from dating_boost.apps.registry import create_adapter, get_adapter, host_loop_app_ids, supported_app_ids

__all__ = ["create_adapter", "get_adapter", "host_loop_app_ids", "supported_app_ids"]
