#!/usr/bin/env python3
from __future__ import annotations

import argparse
import hashlib
import json
import os
import shutil
import subprocess
import sys
import time
from pathlib import Path
from typing import Any

from dating_boost.apps.registry import supported_app_ids
from dating_boost.core.draft_evidence import UserMemoryRepository
from dating_boost.core.live_send_contract import target_binding_structural_evidence_present, validate_live_send_contract
from dating_boost.core.managed_gui_send import (
    ManagedGuiSendError, ManagedGuiSendRunner, _managed_gui_send_required_evidence, _validate_managed_sequence_visual_confirmation,
    _work_item_payload_text,
)
from dating_boost.core.operator import DEFAULT_MESSAGE_LIST_SCAN_BOUNDARY, OperatorRepository
from dating_boost.core.production_store import ProductionDataStore
from dating_boost.core.relationship_report import (
    RELATIONSHIP_PROGRESS_NEXT_ACTION,
    build_relationship_progress_report,
)
from dating_boost.core.runtime_scope import RuntimeScopeRepository
from dating_boost.core.safety import SafetyRepository
from dating_boost.core.support import SupportLogRepository
from dating_boost.perception.observations import ProfileObservation


ROOT = Path(__file__).resolve().parents[1]
DEFAULT_DATA_DIR = Path(".local") / "dating-boost-host-loop"
DEFAULT_FIXTURE_NOW = "2026-05-26T00:00:00Z"
REPORT_FINAL_STATUSES = {"wait", "blocked", "handoff", "scheduled_wait", "stopped", "error"}
MESSAGE_SEQUENCE_SECONDS_PER_MESSAGE = 20
IPHONE_MIRRORING_STRUCTURAL_BINDING_APP_IDS = {"tinder", "bumble"}



class HostLoopError(Exception):
    pass

class HostLoopCommandError(RuntimeError):
    def __init__(self, command: tuple[str, ...], payload: dict[str, Any], returncode: int):
        self.command = command
        self.payload = payload
        self.returncode = returncode
        reason = payload.get("reason") or payload.get("status") or "unknown_cli_error"
        super().__init__(f"dating-boost {' '.join(command)} failed: {reason}")

__all__ = [
    'annotations', 'argparse', 'hashlib', 'json',
    'os', 'shutil', 'subprocess', 'sys',
    'time', 'Path', 'Any', 'supported_app_ids',
    'UserMemoryRepository', 'target_binding_structural_evidence_present', 'validate_live_send_contract', 'ManagedGuiSendError',
    'ManagedGuiSendRunner', '_managed_gui_send_required_evidence', '_validate_managed_sequence_visual_confirmation', '_work_item_payload_text',
    'DEFAULT_MESSAGE_LIST_SCAN_BOUNDARY', 'OperatorRepository', 'ProductionDataStore', 'RELATIONSHIP_PROGRESS_NEXT_ACTION',
    'build_relationship_progress_report', 'RuntimeScopeRepository', 'SafetyRepository', 'SupportLogRepository',
    'ProfileObservation', 'ROOT', 'DEFAULT_DATA_DIR', 'DEFAULT_FIXTURE_NOW',
    'REPORT_FINAL_STATUSES', 'MESSAGE_SEQUENCE_SECONDS_PER_MESSAGE', 'IPHONE_MIRRORING_STRUCTURAL_BINDING_APP_IDS', 'HostLoopError',
    'HostLoopCommandError',
]
