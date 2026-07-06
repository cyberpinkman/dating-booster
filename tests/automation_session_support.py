import json
import os
import tempfile
import unittest
from contextlib import redirect_stdout
from io import StringIO
from pathlib import Path
from unittest.mock import patch

from dating_boost.cli import main
from dating_boost.core.automation import AutomationRepository, _next_priority_queue, _prioritize_entries
from dating_boost.core.draft_evidence import UserMemoryRepository
from dating_boost.core.memory.models import IdentityTrustStatus, MatchMemoryProjection
from dating_boost.core.memory.repositories import MemoryRepository
from dating_boost.perception.observations import AppObservation
from dating_boost.policy.draft_review import DraftReviewDecision, DraftReviewFinding


FIXTURE_DIR = Path("tests/fixtures/automation")




class AutomationSessionTestCase(unittest.TestCase):
    def setUp(self):
        self._clock_patch = patch.dict(os.environ, {"DATING_BOOST_NOW": "2026-05-26T00:00:00Z"})
        self._clock_patch.start()

    def tearDown(self):
        self._clock_patch.stop()

    def _init_profile(self, data_dir):
        self._run([
            "init-profile",
            "--data-dir",
            str(data_dir),
            "--input",
            "tests/fixtures/intelligence/user_profile.json",
        ])
        self._run([
            "user",
            "ingest-profile",
            "--data-dir",
            str(data_dir),
            "--input",
            "tests/fixtures/intelligence/user_dating_profile.json",
        ])
        self._run([
            "user",
            "ingest-interview",
            "--data-dir",
            str(data_dir),
            "--input",
            "tests/fixtures/intelligence/user_self_interview.json",
        ])
        UserMemoryRepository(data_dir).ensure_profile_source(
            app_id="tinder",
            runtime="default",
            observed_at="2026-05-26T00:00:00Z",
        )

    def _run(self, argv):
        output = StringIO()
        with redirect_stdout(output):
            exit_code = main(argv)
        text = output.getvalue()
        return exit_code, json.loads(text), text

    def _run_text(self, argv):
        output = StringIO()
        with redirect_stdout(output):
            exit_code = main(argv)
        return exit_code, output.getvalue()

    def _write_json(self, path, payload):
        path.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")

def _contact_exchange_scan_batch():
    return {
        "schema_version": 1,
        "session_id": "session_fixture_contact_exchange",
        "app_id": "tinder",
        "captured_at": "2026-05-26T10:00:00Z",
        "scan_budget": 1,
        "message_list_snapshot": {
            "entries": [
                {
                    "candidate_key": "row_iris",
                    "visible_name": "Iris",
                    "latest_preview": "没换呢",
                    "latest_preview_hash": "preview_iris_contact",
                    "timestamp_cue": "刚刚",
                    "unread_cue": "present",
                    "position": 1,
                }
            ]
        },
        "thread_observations": [
            {
                "candidate_key": "row_iris",
                "assessment": {
                    "schema_version": 1,
                    "latest_match_message": "没换呢",
                    "latest_user_message": "你现在的 wx 是什么",
                    "latest_inbound_fingerprint": "iris:in:wx-not-changed",
                    "reply_window_status": "open",
                    "continuation_opportunity": "yes",
                    "appointment_stage": "none",
                    "recommended_next": "handoff",
                    "confidence": "high",
                    "evidence": "The thread has moved into contact exchange.",
                    "risk_flags": ["contact_exchange"],
                },
                "observation": {
                    "observation_id": "obs_iris_contact_001",
                    "source_type": "manual_fixture",
                    "app_id": "tinder",
                    "adapter_id": "codex.manual.v1",
                    "captured_at": "2026-05-26T10:00:00Z",
                    "page_type": "chat_thread",
                    "page_confidence": "high",
                    "match_identity_hints": {
                        "visible_name": "Iris",
                        "profile_cues": ["friend_test_match"],
                        "conversation_fingerprint": "iris-contact-exchange",
                        "evidence": "Visible Iris test thread.",
                    },
                    "profile_observation": {
                        "profile_text": "",
                        "photo_cues": [],
                        "hook_candidates": [],
                    },
                    "conversation_observation": {
                        "visible_messages": [
                            {"sender": "user", "text": "你现在的 wx 是什么"},
                            {"sender": "match", "text": "没换呢"},
                        ],
                        "input_state": "empty",
                        "thread_cues": ["contact_exchange"],
                    },
                    "element_observations": [],
                    "exception_state": "none",
                    "provenance": {
                        "evidence": "Fixture thread observation.",
                        "redaction_status": "redacted",
                    },
                    "raw_ref": None,
                },
            }
        ],
    }

def _nudge_draft():
    return {
        "best_reply": "刚想起来，你上次说的荒诞喜剧是哪部来着",
        "safer_reply": "刚想起来，你上次说的那种喜剧有推荐吗",
        "bolder_reply": "刚想起来，这题我还挺想抄个片单的",
        "why_this_works": "It lightly reopens the last movie thread.",
        "situation_read": "The thread was open but paused after the user replied.",
        "conversation_move": "nudge_later",
        "hook_source": "conversation_thread",
        "naturalness_notes": ["short", "keeps the old topic"],
        "followup_if_match_replies": "If she names a movie, reply around that title.",
        "risk_flags": [],
        "missing_info": [],
        "mode_notes": "Adaptive mode.",
        "persona_divergence": "low",
        "stance_divergence": "low",
        "draft_generation_id": "draft_generation_nudge_fixture",
        "draft_self_review_summary": {
            "schema_version": 1,
            "ai_or_weird_probability": 0,
            "status": "ok",
            "source": "unit_fixture",
        },
    }
