from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import pytest


pytestmark = pytest.mark.managed_critical


def test_offline_benchmark_comparison_matrix_and_scope(tmp_path: Path) -> None:
    script = Path(__file__).resolve().parents[1] / "scripts" / "managed_run_benchmark.py"
    result = subprocess.run(
        [sys.executable, str(script)], cwd=tmp_path, text=True, capture_output=True, check=True, timeout=30,
    )
    report = json.loads(result.stdout)
    assert report["workload"] == "synthetic"
    assert report["live_gui"] is report["live_api"] is False
    assert report["storage"] == "in_memory"
    assert report["measurement"] == "operation_counts_only"
    assert not list(tmp_path.iterdir())
    assert set(report["workloads"]) == {"all_reply", "mixed_reply_wait_handoff"}
    for name, workload in report["workloads"].items():
        assert workload["thread_count"] == 5
        mixed = name == "mixed_reply_wait_handoff"
        assert set(workload["variants"]) == {"legacy_per_thread_scan", "queued_without_jev", "queued_with_jev"}
        for variant_name, variant in workload["variants"].items():
            queued = variant_name != "legacy_per_thread_scan"
            jev = variant_name == "queued_with_jev"
            counts = variant["operations"]
            assert counts["message_list_scans"] == (2 if queued else 6)
            assert counts["processing_scans"] == (1 if queued else 5)
            assert counts["terminal_no_work_scans"] == 1
            assert counts["thread_opens"] == counts["thread_reads"] == 5
            assert counts["draft_planner_calls"] == (2 if mixed and jev else 5)
            assert counts["semantic_requests_scripted"] == (5 if jev else 0)
            assert counts["semantic_questions_scripted"] == 2 * counts["semantic_requests_scripted"]
            assert counts["live_http_requests"] == 0
            assert variant["terminal_status"] == "no_work"
            assert variant["outcomes"] == {
                "confirmed": 2 if mixed else 5,
                "wait": 2 if mixed and jev else 0,
                "handoff": (1 if jev else 3) if mixed else 0,
            }
            assert variant["synthetic_safety_seam_calls"] == {
                seam: variant["outcomes"]["confirmed"]
                for seam in ("composer_observe", "exact_stage", "return_only_click", "fresh_post_send_observe")
            }

    assert set(report["burst_scenarios"]) == {"2_messages", "3_messages"}
    seams = ["composer_observe", "exact_stage", "return_only_click", "fresh_post_send_observe"]
    for message_count in (2, 3):
        scenarios = report["burst_scenarios"][f"{message_count}_messages"]
        assert set(scenarios) == {"without_jev", "with_jev"}
        for name, variant in scenarios.items():
            jev = name == "with_jev"
            counts = variant["operations"]
            assert counts["thread_reads"] == counts["thread_opens"] == 1
            assert counts["decision_calls"] == counts["draft_planner_calls"] == 1
            assert counts["semantic_requests_scripted"] == int(jev)
            assert counts["semantic_questions_scripted"] == 2 * int(jev)
            assert counts["live_http_requests"] == 0
            assert variant["terminal_status"] == "no_work"
            assert variant["synthetic_safety_seam_calls"] == dict.fromkeys(seams, message_count)
            burst = variant["burst"]
            assert burst["message_count"] == burst["confirmed_message_count"] == message_count
            assert burst["simulated_planning_seconds"] == 180 > burst["gap_limit_seconds"]
            assert burst["click_times_virtual_seconds"][0] >= 180
            assert burst["click_gaps_virtual_seconds"] == [4] * (message_count - 1)
            assert burst["semantic_requests_between_clicks"] == burst["planner_calls_between_clicks"] == 0
            assert burst["contiguous_action_seams"] is True
            assert burst["operation_order"] == (
                ["message_list_scan", "thread_open", "thread_read", "decide"]
                + (["semantic_request"] if jev else [])
                + ["draft_start", "draft_complete"]
                + seams * message_count
                + ["message_list_scan"]
            )
