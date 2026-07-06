from tests.operator_host_loop_support import (
    AppObservation,
    FIXTURE_DIR,
    HostLoopCommandError,
    HostLoopError,
    HostLoopSupervisor,
    OperatorHostLoopTestCase,
    OperatorRepository,
    Path,
    _action_result_for_work_item,
    _audit_binding,
    _bumble_conversation_png,
    _iphone_current_thread_target_binding,
    _target_binding_for_work_item,
    _tashuo_mac_ios_app_conversation_with_messages_png,
    _thread_template,
    _tinder_conversation_send_button_png,
    _validate_managed_sequence_visual_confirmation,
    _wechat_managed_work_item,
    _write_draft_review_audit,
    argparse,
    hashlib,
    json,
    os,
    patch,
    shutil,
    subprocess,
    sys,
    tempfile,
)

class OperatorHostLoopTashuoSendTests(OperatorHostLoopTestCase):
    def test_managed_tashuo_live_send_uses_mac_ios_runtime_when_structural_binding_and_evidence_pass(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            data_dir = root / "data"
            work_dir = root / "work"
            auth_path = root / "tashuo_auth.json"
            payload_text = "今晚可以聊十分钟吗？"
            payload_hash = hashlib.sha256(payload_text.encode("utf-8")).hexdigest()
            self._write_json(auth_path, {
                "schema_version": 1,
                "authorization_id": "auth_tashuo_live",
                "scope": "send_chat_messages",
                "app_id": "tashuo",
                "expires_at": "2099-01-01T00:00:00Z",
                "allowed_actions": ["send_message"],
                "autonomous_send": True,
                "live_send": True,
                "requires_post_action_verification": True,
                "revoked_at": None,
            })
            supervisor = HostLoopSupervisor(
                argparse.Namespace(
                    data_dir=data_dir,
                    authorization=auth_path,
                    goal=None,
                    availability=None,
                    app_id="tashuo",
                    send_mode="live",
                    managed_gui_send=True,
                    harness_runtime="mac-ios-app",
                    work_dir=work_dir,
                    max_steps=1,
                    once=False,
                    json=True,
                    fixture_host=None,
                    wait_timeout=None,
                    poll_interval=1.0,
                    adapter_package=None,
                    skill_package=None,
                )
            )
            work_dir.mkdir(parents=True, exist_ok=True)
            work_item = _wechat_managed_work_item(payload_text, payload_hash)
            work_item["match_id"] = "match_tashuo"
            work_item["candidate_key"] = "tashuo_ada"
            work_item["autonomous_audit_binding"] = _audit_binding(
                authorization_id="auth_tashuo_live",
                target_match_id="match_tashuo",
                payload_hash=payload_hash,
            )
            work_item["target_binding"] = {
                "binding_type": "current_thread_visual_identity",
                "target_match_id": "match_tashuo",
                "candidate_key": "tashuo_ada",
                "visible_name": "Ada",
                "conversation_fingerprint": "ada-latest",
                "thread_evidence": {
                    "observation_id": "obs_before",
                    "screen_state": "tashuo_conversation",
                    "latest_inbound_fingerprint": "ada:in:latest",
                    "visual_anchor_hash": "0123456789abcdef",
                },
            }
            recorded_result: dict[str, object] = {}

            def fake_run_cli_json(*args: str, allow_error: bool = False, **kwargs: object) -> dict[str, object]:
                if len(args) >= 3 and args[0] == "harness" and args[1] == "tashuo" and "send-message" in args:
                    self.assertIn("--runtime", args)
                    self.assertEqual(args[args.index("--runtime") + 1], "mac-ios-app")
                    self.assertIn("--action-request", args)
                    action_path = Path(args[args.index("--action-request") + 1])
                    action_request = json.loads(action_path.read_text(encoding="utf-8"))
                    self.assertEqual(action_request["app_id"], "tashuo")
                    self.assertEqual(action_request["target_binding"]["binding_type"], "current_thread_visual_identity")
                    return {
                        "schema_version": 2,
                        "status": "ok",
                        "app_id": "tashuo",
                        "harness_backend": "mac_ios_app",
                        "action": "send_message",
                        "post_action_observation_id": "gui_post_send_tashuo_mac_1234",
                        "evidence": {
                            "staged_text_verified": True,
                            "staged_exact_text_verified": True,
                            "staged_exact_text_ocr_verified": True,
                            "input_cleared_after_send": True,
                            "post_action_screen_captured": True,
                            "outbound_message_verified": True,
                            "outbound_exact_text_ocr_verified": True,
                        },
                    }
                if args[:2] == ("operator", "record-action-result"):
                    result_path = Path(args[args.index("--input") + 1])
                    recorded_result.update(json.loads(result_path.read_text(encoding="utf-8")))
                    return {"schema_version": 1, "status": "ok", "recorded": True}
                raise AssertionError(args)

            with patch.object(supervisor, "_run_cli_json", fake_run_cli_json):
                _write_draft_review_audit(data_dir, work_item)
                result = supervisor._handle_managed_gui_send(work_item)

        self.assertIsNone(result)
        self.assertEqual(recorded_result["result_status"], "succeeded")
        self.assertEqual(recorded_result["post_action_observation_id"], "gui_post_send_tashuo_mac_1234")
        self.assertTrue(recorded_result["evidence"]["managed_gui_send"])
        self.assertTrue(recorded_result["evidence"]["outbound_message_verified"])

    def test_managed_tashuo_mac_ios_live_send_sends_message_sequence_as_ordered_gui_calls(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            data_dir = root / "data"
            work_dir = root / "work"
            auth_path = root / "tashuo_auth.json"
            messages = [
                "慢热联盟可以成立",
                "不过我更好奇你做运营的时候，是不是也先观察局面",
                "等判断差不多了再开始出手",
            ]
            payload_text = "\n".join(messages)
            payload_hash = hashlib.sha256(
                json.dumps(
                    {"payload_format": "message_sequence", "messages": messages},
                    ensure_ascii=False,
                    sort_keys=True,
                    separators=(",", ":"),
                ).encode("utf-8")
            ).hexdigest()
            self._write_json(auth_path, {
                "schema_version": 1,
                "authorization_id": "auth_tashuo_live",
                "scope": "send_chat_messages",
                "app_id": "tashuo",
                "expires_at": "2099-01-01T00:00:00Z",
                "allowed_actions": ["send_message"],
                "autonomous_send": True,
                "live_send": True,
                "requires_post_action_verification": True,
                "revoked_at": None,
            })
            supervisor = HostLoopSupervisor(
                argparse.Namespace(
                    data_dir=data_dir,
                    authorization=auth_path,
                    goal=None,
                    availability=None,
                    app_id="tashuo",
                    send_mode="live",
                    managed_gui_send=True,
                    harness_runtime="mac-ios-app",
                    work_dir=work_dir,
                    max_steps=1,
                    once=False,
                    json=True,
                    fixture_host=None,
                    wait_timeout=None,
                    poll_interval=1.0,
                    adapter_package=None,
                    skill_package=None,
                )
            )
            work_dir.mkdir(parents=True, exist_ok=True)
            work_item = _wechat_managed_work_item(payload_text, payload_hash)
            work_item.update({
                "work_item_id": "work_tashuo_send_sequence",
                "action_request_id": "act_tashuo_send_sequence",
                "match_id": "match_tashuo",
                "candidate_key": "tashuo_duoduo",
                "payload_format": "message_sequence",
                "payload_messages": [
                    {
                        "index": index,
                        "text": text,
                        "message_hash": hashlib.sha256(text.encode("utf-8")).hexdigest(),
                        "character_count": len(text),
                    }
                    for index, text in enumerate(messages, start=1)
                ],
                "autonomous_audit_binding": _audit_binding(
                    authorization_id="auth_tashuo_live",
                    target_match_id="match_tashuo",
                    payload_hash=payload_hash,
                ),
                "target_binding": {
                    "binding_type": "current_thread_visual_identity",
                    "target_match_id": "match_tashuo",
                    "candidate_key": "tashuo_duoduo",
                    "visible_name": "朵朵",
                    "conversation_fingerprint": "duoduo-hi-nihao",
                    "thread_evidence": {
                        "observation_id": "obs_before",
                        "screen_state": "tashuo_conversation",
                        "latest_inbound_fingerprint": "duoduo:in:nihao",
                        "visual_anchor_hash": "0123456789abcdef",
                    },
                },
            })
            progress_path = work_dir / "managed_sequence_progress.work_tashuo_send_sequence.json"
            sent_texts: list[str] = []
            recorded_result: dict[str, object] = {}

            def fake_run_cli_json(*args: str, allow_error: bool = False, **kwargs: object) -> dict[str, object]:
                if len(args) >= 3 and args[0] == "harness" and args[1] == "tashuo" and "send-message" in args:
                    self.assertIn("--runtime", args)
                    self.assertEqual(args[args.index("--runtime") + 1], "mac-ios-app")
                    if not sent_texts:
                        self.assertTrue(progress_path.exists())
                        progress = json.loads(progress_path.read_text(encoding="utf-8"))
                        self.assertEqual(progress["sequence_started_at"], "2026-06-12T00:00:00Z")
                        self.assertEqual(progress["message_sequence_window_seconds"], 60)
                    self.assertEqual(kwargs.get("timeout_seconds"), 60.0)
                    text_path = Path(args[args.index("--text-file") + 1])
                    action_path = Path(args[args.index("--action-request") + 1])
                    message_text = text_path.read_text(encoding="utf-8")
                    action_request = json.loads(action_path.read_text(encoding="utf-8"))
                    sent_texts.append(message_text)
                    self.assertEqual(action_request["payload_format"], "single_message")
                    self.assertEqual(action_request["payload_text"], message_text)
                    self.assertEqual(action_request["payload_hash"], hashlib.sha256(message_text.encode("utf-8")).hexdigest())
                    self.assertEqual(action_request["target_binding"]["binding_type"], "current_thread_visual_identity")
                    return {
                        "schema_version": 2,
                        "status": "ok",
                        "app_id": "tashuo",
                        "harness_backend": "mac_ios_app",
                        "action": "send_message",
                        "post_action_observation_id": f"gui_post_send_tashuo_mac_{len(sent_texts)}",
                        "evidence": {
                            "staged_text_verified": True,
                            "staged_exact_text_verified": True,
                            "staged_exact_text_ocr_verified": True,
                            "input_cleared_after_send": True,
                            "post_action_screen_captured": True,
                            "outbound_message_verified": True,
                            "outbound_exact_text_ocr_verified": True,
                        },
                    }
                if args[:2] == ("operator", "record-action-result"):
                    result_path = Path(args[args.index("--input") + 1])
                    recorded_result.update(json.loads(result_path.read_text(encoding="utf-8")))
                    return {"schema_version": 1, "status": "ok", "recorded": True}
                raise AssertionError(args)

            with patch.dict(os.environ, {"DATING_BOOST_NOW": "2026-06-12T00:00:00Z"}), patch.object(
                supervisor,
                "_run_cli_json",
                fake_run_cli_json,
            ):
                _write_draft_review_audit(data_dir, work_item)
                result = supervisor._handle_managed_gui_send(work_item)

        self.assertIsNone(result)
        self.assertEqual(sent_texts, messages)
        self.assertEqual(recorded_result["payload_hash"], payload_hash)
        self.assertEqual(recorded_result["message_count"], 3)
        self.assertEqual(recorded_result["payload_format"], "message_sequence")
        self.assertEqual(recorded_result["post_action_observation_id"], "gui_post_send_tashuo_mac_3")
        self.assertEqual(recorded_result["message_sequence_window_seconds"], 60)
        self.assertEqual(recorded_result["message_sequence_started_at"], "2026-06-12T00:00:00Z")
        self.assertEqual(recorded_result["message_sequence_last_sent_at"], "2026-06-12T00:00:00Z")
        self.assertEqual(recorded_result["message_sequence_elapsed_seconds"], 0.0)
        self.assertTrue(recorded_result["evidence"]["message_sequence_within_window"])
        self.assertEqual(
            recorded_result["message_results"],
            [
                {
                    "index": 1,
                    "message_hash": hashlib.sha256(messages[0].encode("utf-8")).hexdigest(),
                    "character_count": len(messages[0]),
                    "post_action_observation_id": "gui_post_send_tashuo_mac_1",
                    "status": "ok",
                    "evidence": {
                        "staged_text_verified": True,
                        "staged_exact_text_verified": True,
                        "input_cleared_after_send": True,
                        "post_action_screen_captured": True,
                        "outbound_message_verified": True,
                        "outbound_exact_text_verified": True,
                    },
                    "sent_at": "2026-06-12T00:00:00Z",
                },
                {
                    "index": 2,
                    "message_hash": hashlib.sha256(messages[1].encode("utf-8")).hexdigest(),
                    "character_count": len(messages[1]),
                    "post_action_observation_id": "gui_post_send_tashuo_mac_2",
                    "status": "ok",
                    "evidence": {
                        "staged_text_verified": True,
                        "staged_exact_text_verified": True,
                        "input_cleared_after_send": True,
                        "post_action_screen_captured": True,
                        "outbound_message_verified": True,
                        "outbound_exact_text_verified": True,
                    },
                    "sent_at": "2026-06-12T00:00:00Z",
                },
                {
                    "index": 3,
                    "message_hash": hashlib.sha256(messages[2].encode("utf-8")).hexdigest(),
                    "character_count": len(messages[2]),
                    "post_action_observation_id": "gui_post_send_tashuo_mac_3",
                    "status": "ok",
                    "evidence": {
                        "staged_text_verified": True,
                        "staged_exact_text_verified": True,
                        "input_cleared_after_send": True,
                        "post_action_screen_captured": True,
                        "outbound_message_verified": True,
                        "outbound_exact_text_verified": True,
                    },
                    "sent_at": "2026-06-12T00:00:00Z",
                },
            ],
        )

    def test_managed_tashuo_mac_ios_message_sequence_failure_reports_completed_count(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            data_dir = root / "data"
            work_dir = root / "work"
            auth_path = root / "tashuo_auth.json"
            messages = ["第一条", "第二条", "第三条"]
            payload_text = "\n".join(messages)
            payload_hash = hashlib.sha256(
                json.dumps(
                    {"payload_format": "message_sequence", "messages": messages},
                    ensure_ascii=False,
                    sort_keys=True,
                    separators=(",", ":"),
                ).encode("utf-8")
            ).hexdigest()
            self._write_json(auth_path, {
                "schema_version": 1,
                "authorization_id": "auth_tashuo_live",
                "scope": "send_chat_messages",
                "app_id": "tashuo",
                "expires_at": "2099-01-01T00:00:00Z",
                "allowed_actions": ["send_message"],
                "autonomous_send": True,
                "live_send": True,
                "requires_post_action_verification": True,
                "revoked_at": None,
            })
            supervisor = HostLoopSupervisor(
                argparse.Namespace(
                    data_dir=data_dir,
                    authorization=auth_path,
                    goal=None,
                    availability=None,
                    app_id="tashuo",
                    send_mode="live",
                    managed_gui_send=True,
                    harness_runtime="mac-ios-app",
                    work_dir=work_dir,
                    max_steps=1,
                    once=False,
                    json=True,
                    fixture_host=None,
                    wait_timeout=None,
                    poll_interval=1.0,
                    adapter_package=None,
                    skill_package=None,
                )
            )
            work_dir.mkdir(parents=True, exist_ok=True)
            work_item = _wechat_managed_work_item(payload_text, payload_hash)
            work_item.update({
                "work_item_id": "work_tashuo_send_sequence_failure",
                "action_request_id": "act_tashuo_send_sequence_failure",
                "match_id": "match_tashuo",
                "candidate_key": "tashuo_duoduo",
                "payload_format": "message_sequence",
                "payload_messages": [
                    {
                        "index": index,
                        "text": text,
                        "message_hash": hashlib.sha256(text.encode("utf-8")).hexdigest(),
                        "character_count": len(text),
                    }
                    for index, text in enumerate(messages, start=1)
                ],
                "autonomous_audit_binding": _audit_binding(
                    authorization_id="auth_tashuo_live",
                    target_match_id="match_tashuo",
                    payload_hash=payload_hash,
                ),
                "target_binding": {
                    "binding_type": "current_thread_visual_identity",
                    "target_match_id": "match_tashuo",
                    "candidate_key": "tashuo_duoduo",
                    "conversation_fingerprint": "duoduo-hi-nihao",
                    "thread_evidence": {
                        "observation_id": "obs_before",
                        "screen_state": "tashuo_conversation",
                        "latest_inbound_fingerprint": "duoduo:in:nihao",
                        "visual_anchor_hash": "0123456789abcdef",
                    },
                },
            })
            calls = 0

            def fake_run_cli_json(*args: str, allow_error: bool = False, **kwargs: object) -> dict[str, object]:
                nonlocal calls
                if len(args) >= 3 and args[0] == "harness" and args[1] == "tashuo" and "send-message" in args:
                    calls += 1
                    if calls == 1:
                        return {
                            "schema_version": 2,
                            "status": "ok",
                            "post_action_observation_id": "gui_post_send_tashuo_mac_1",
                            "evidence": {
                                "staged_text_verified": True,
                                "staged_exact_text_verified": True,
                                "input_cleared_after_send": True,
                                "post_action_screen_captured": True,
                                "outbound_message_verified": True,
                                "outbound_exact_text_verified": True,
                            },
                        }
                    return {
                        "schema_version": 2,
                        "status": "blocked",
                        "reason": "outbound_message_not_verified",
                        "evidence": {"staged_text_verified": True},
                    }
                raise AssertionError(args)

            with patch.object(supervisor, "_run_cli_json", fake_run_cli_json):
                _write_draft_review_audit(data_dir, work_item)
                result = supervisor._handle_managed_gui_send(work_item)

        self.assertEqual(result["status"], "blocked")
        self.assertEqual(result["reason"], "outbound_message_not_verified")
        self.assertEqual(result["completed_message_count"], 1)
        self.assertEqual(result["failed_message_index"], 2)
        self.assertEqual(result["message_results"][0]["post_action_observation_id"], "gui_post_send_tashuo_mac_1")
        self.assertEqual(calls, 2)

    def test_managed_tashuo_mac_ios_sequence_accepts_already_sent_prefix(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            data_dir = root / "data"
            work_dir = root / "work"
            auth_path = root / "tashuo_auth.json"
            messages = ["你好啊，接上了", "看你是做运营的，我有点好奇"]
            payload_text = "\n".join(messages)
            payload_hash = hashlib.sha256(
                json.dumps(
                    {"payload_format": "message_sequence", "messages": messages},
                    ensure_ascii=False,
                    sort_keys=True,
                    separators=(",", ":"),
                ).encode("utf-8")
            ).hexdigest()
            self._write_json(auth_path, {
                "schema_version": 1,
                "authorization_id": "auth_tashuo_live",
                "scope": "send_chat_messages",
                "app_id": "tashuo",
                "expires_at": "2099-01-01T00:00:00Z",
                "allowed_actions": ["send_message"],
                "autonomous_send": True,
                "live_send": True,
                "requires_post_action_verification": True,
                "revoked_at": None,
            })
            supervisor = HostLoopSupervisor(
                argparse.Namespace(
                    data_dir=data_dir,
                    authorization=auth_path,
                    goal=None,
                    availability=None,
                    app_id="tashuo",
                    send_mode="live",
                    managed_gui_send=True,
                    harness_runtime="mac-ios-app",
                    work_dir=work_dir,
                    max_steps=1,
                    once=False,
                    json=True,
                    fixture_host=None,
                    wait_timeout=None,
                    poll_interval=1.0,
                    adapter_package=None,
                    skill_package=None,
                )
            )
            work_dir.mkdir(parents=True, exist_ok=True)
            work_item = _wechat_managed_work_item(payload_text, payload_hash)
            work_item.update({
                "work_item_id": "work_tashuo_send_sequence_idempotent",
                "action_request_id": "act_tashuo_send_sequence_idempotent",
                "match_id": "match_tashuo",
                "candidate_key": "tashuo_duoduo",
                "payload_format": "message_sequence",
                "payload_messages": [
                    {
                        "index": index,
                        "text": text,
                        "message_hash": hashlib.sha256(text.encode("utf-8")).hexdigest(),
                        "character_count": len(text),
                    }
                    for index, text in enumerate(messages, start=1)
                ],
                "autonomous_audit_binding": _audit_binding(
                    authorization_id="auth_tashuo_live",
                    target_match_id="match_tashuo",
                    payload_hash=payload_hash,
                ),
                "target_binding": {
                    "binding_type": "current_thread_visual_identity",
                    "target_match_id": "match_tashuo",
                    "candidate_key": "tashuo_duoduo",
                    "conversation_fingerprint": "duoduo-hi-nihao",
                    "thread_evidence": {
                        "observation_id": "obs_before",
                        "screen_state": "tashuo_conversation",
                        "latest_inbound_fingerprint": "duoduo:in:nihao",
                        "visual_anchor_hash": "0123456789abcdef",
                    },
                },
            })
            calls: list[str] = []
            recorded_result: dict[str, object] = {}
            second_action_request: dict[str, object] = {}

            def fake_run_cli_json(*args: str, allow_error: bool = False, **kwargs: object) -> dict[str, object]:
                if len(args) >= 3 and args[0] == "harness" and args[1] == "tashuo" and "send-message" in args:
                    text_path = Path(args[args.index("--text-file") + 1])
                    action_path = Path(args[args.index("--action-request") + 1])
                    message_text = text_path.read_text(encoding="utf-8")
                    calls.append(message_text)
                    if len(calls) == 1:
                        return {
                            "schema_version": 2,
                            "status": "ok",
                            "already_sent": True,
                            "post_action_observation_id": "gui_post_send_tashuo_mac_existing_1",
                            "current_thread_visual_anchor": {
                                "status": "ok",
                                "screen_state": "tashuo_conversation",
                                "visual_anchor_hash": "fedcba9876543210",
                                "visual_anchor_region": {"x1": 0.0, "y1": 0.08, "x2": 1.0, "y2": 0.84},
                            },
                            "evidence": {
                                "input_cleared_after_send": True,
                                "post_action_screen_captured": True,
                                "outbound_message_verified": True,
                                "outbound_exact_text_verified": True,
                                "outbound_exact_text_ax_verified": True,
                            },
                        }
                    second_action_request.update(json.loads(action_path.read_text(encoding="utf-8")))
                    return {
                        "schema_version": 2,
                        "status": "ok",
                        "post_action_observation_id": "gui_post_send_tashuo_mac_2",
                        "evidence": {
                            "staged_text_verified": True,
                            "staged_exact_text_verified": True,
                            "input_cleared_after_send": True,
                            "post_action_screen_captured": True,
                            "outbound_message_verified": True,
                            "outbound_exact_text_verified": True,
                        },
                    }
                if args[:2] == ("operator", "record-action-result"):
                    result_path = Path(args[args.index("--input") + 1])
                    recorded_result.update(json.loads(result_path.read_text(encoding="utf-8")))
                    return {"schema_version": 1, "status": "ok", "recorded": True}
                raise AssertionError(args)

            with patch.object(supervisor, "_run_cli_json", fake_run_cli_json):
                _write_draft_review_audit(data_dir, work_item)
                result = supervisor._handle_managed_gui_send(work_item)

        self.assertIsNone(result)
        self.assertEqual(calls, messages)
        self.assertTrue(recorded_result["message_results"][0]["already_sent"])
        self.assertFalse(recorded_result["message_results"][0]["evidence"]["staged_text_verified"])
        self.assertEqual(
            second_action_request["target_binding"]["thread_evidence"]["visual_anchor_hash"],
            "fedcba9876543210",
        )
        self.assertEqual(
            second_action_request["target_binding"]["thread_evidence"]["observation_id"],
            "gui_post_send_tashuo_mac_existing_1",
        )
        self.assertEqual(recorded_result["post_action_observation_id"], "gui_post_send_tashuo_mac_2")

    def test_managed_tashuo_mac_ios_sequence_resume_skips_recorded_progress_prefix(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            data_dir = root / "data"
            work_dir = root / "work"
            auth_path = root / "tashuo_auth.json"
            messages = ["第一条", "第二条", "第三条"]
            payload_text = "\n".join(messages)
            payload_hash = hashlib.sha256(
                json.dumps(
                    {"payload_format": "message_sequence", "messages": messages},
                    ensure_ascii=False,
                    sort_keys=True,
                    separators=(",", ":"),
                ).encode("utf-8")
            ).hexdigest()
            self._write_json(auth_path, {
                "schema_version": 1,
                "authorization_id": "auth_tashuo_live",
                "scope": "send_chat_messages",
                "app_id": "tashuo",
                "expires_at": "2099-01-01T00:00:00Z",
                "allowed_actions": ["send_message"],
                "autonomous_send": True,
                "live_send": True,
                "requires_post_action_verification": True,
                "revoked_at": None,
            })
            supervisor = HostLoopSupervisor(
                argparse.Namespace(
                    data_dir=data_dir,
                    authorization=auth_path,
                    goal=None,
                    availability=None,
                    app_id="tashuo",
                    send_mode="live",
                    managed_gui_send=True,
                    harness_runtime="mac-ios-app",
                    work_dir=work_dir,
                    max_steps=1,
                    once=False,
                    json=True,
                    fixture_host=None,
                    wait_timeout=None,
                    poll_interval=1.0,
                    adapter_package=None,
                    skill_package=None,
                )
            )
            work_dir.mkdir(parents=True, exist_ok=True)
            work_item = _wechat_managed_work_item(payload_text, payload_hash)
            work_item.update({
                "work_item_id": "work_tashuo_send_sequence_resume_progress",
                "action_request_id": "act_tashuo_send_sequence_resume_progress",
                "match_id": "match_tashuo",
                "candidate_key": "tashuo_duoduo",
                "payload_format": "message_sequence",
                "payload_messages": [
                    {
                        "index": index,
                        "text": text,
                        "message_hash": hashlib.sha256(text.encode("utf-8")).hexdigest(),
                        "character_count": len(text),
                    }
                    for index, text in enumerate(messages, start=1)
                ],
                "autonomous_audit_binding": _audit_binding(
                    authorization_id="auth_tashuo_live",
                    target_match_id="match_tashuo",
                    payload_hash=payload_hash,
                ),
                "target_binding": {
                    "binding_type": "current_thread_visual_identity",
                    "target_match_id": "match_tashuo",
                    "candidate_key": "tashuo_duoduo",
                    "conversation_fingerprint": "duoduo-progress",
                    "thread_evidence": {
                        "observation_id": "obs_before",
                        "screen_state": "tashuo_conversation",
                        "latest_inbound_fingerprint": "duoduo:in",
                        "visual_anchor_hash": "old",
                    },
                },
            })
            progress_path = work_dir / "managed_sequence_progress.work_tashuo_send_sequence_resume_progress.json"
            self._write_json(progress_path, {
                "schema_version": 1,
                "work_item_id": work_item["work_item_id"],
                "action_request_id": work_item["action_request_id"],
                "payload_hash": payload_hash,
                "completed_message_count": 2,
                "sequence_started_at": "2026-06-12T00:00:00Z",
                "last_message_sent_at": "2026-06-12T00:00:10Z",
                "message_sequence_window_seconds": 60,
                "target_binding": {
                    "binding_type": "current_thread_visual_identity",
                    "target_match_id": "match_tashuo",
                    "candidate_key": "tashuo_duoduo",
                    "conversation_fingerprint": "duoduo-progress",
                    "thread_evidence": {
                        "observation_id": "gui_post_send_2",
                        "screen_state": "tashuo_conversation",
                        "latest_inbound_fingerprint": "duoduo:in",
                        "visual_anchor_hash": "fresh",
                    },
                },
                "message_results": [
                    {
                        "index": 1,
                        "message_hash": hashlib.sha256(messages[0].encode("utf-8")).hexdigest(),
                        "character_count": len(messages[0]),
                        "post_action_observation_id": "gui_post_send_1",
                        "status": "ok",
                        "evidence": {"outbound_exact_text_verified": True},
                    },
                    {
                        "index": 2,
                        "message_hash": hashlib.sha256(messages[1].encode("utf-8")).hexdigest(),
                        "character_count": len(messages[1]),
                        "post_action_observation_id": "gui_post_send_2",
                        "status": "ok",
                        "evidence": {"outbound_exact_text_verified": True},
                    },
                ],
            })
            sent_texts: list[str] = []
            recorded_result: dict[str, object] = {}
            third_action_request: dict[str, object] = {}

            def fake_run_cli_json(*args: str, allow_error: bool = False, **kwargs: object) -> dict[str, object]:
                if len(args) >= 3 and args[0] == "harness" and args[1] == "tashuo" and "send-message" in args:
                    text_path = Path(args[args.index("--text-file") + 1])
                    action_path = Path(args[args.index("--action-request") + 1])
                    sent_texts.append(text_path.read_text(encoding="utf-8"))
                    third_action_request.update(json.loads(action_path.read_text(encoding="utf-8")))
                    return {
                        "schema_version": 2,
                        "status": "ok",
                        "post_action_observation_id": "gui_post_send_3",
                        "evidence": {
                            "staged_text_verified": True,
                            "staged_exact_text_verified": True,
                            "input_cleared_after_send": True,
                            "post_action_screen_captured": True,
                            "outbound_message_verified": True,
                            "outbound_exact_text_verified": True,
                        },
                    }
                if args[:2] == ("operator", "record-action-result"):
                    result_path = Path(args[args.index("--input") + 1])
                    recorded_result.update(json.loads(result_path.read_text(encoding="utf-8")))
                    return {"schema_version": 1, "status": "ok", "recorded": True}
                raise AssertionError(args)

            with patch.dict(os.environ, {"DATING_BOOST_NOW": "2026-06-12T00:00:20Z"}), patch.object(
                supervisor,
                "_run_cli_json",
                fake_run_cli_json,
            ):
                _write_draft_review_audit(data_dir, work_item)
                result = supervisor._handle_managed_gui_send(work_item)

        self.assertIsNone(result)
        self.assertEqual(sent_texts, ["第三条"])
        self.assertEqual(third_action_request["target_binding"]["thread_evidence"]["visual_anchor_hash"], "fresh")
        self.assertEqual(recorded_result["message_count"], 3)
        self.assertEqual(recorded_result["message_sequence_window_seconds"], 60)
        self.assertEqual(recorded_result["message_sequence_elapsed_seconds"], 20.0)
        self.assertTrue(recorded_result["evidence"]["message_sequence_within_window"])
        self.assertEqual(len(recorded_result["message_results"]), 3)
        self.assertEqual(recorded_result["post_action_observation_id"], "gui_post_send_3")
        self.assertFalse(progress_path.exists())

    def test_managed_tashuo_mac_ios_sequence_resume_blocks_expired_window(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            data_dir = root / "data"
            work_dir = root / "work"
            auth_path = root / "tashuo_auth.json"
            messages = ["第一条", "第二条", "第三条"]
            payload_text = "\n".join(messages)
            payload_hash = hashlib.sha256(
                json.dumps(
                    {"payload_format": "message_sequence", "messages": messages},
                    ensure_ascii=False,
                    sort_keys=True,
                    separators=(",", ":"),
                ).encode("utf-8")
            ).hexdigest()
            self._write_json(auth_path, {
                "schema_version": 1,
                "authorization_id": "auth_tashuo_live",
                "scope": "send_chat_messages",
                "app_id": "tashuo",
                "expires_at": "2099-01-01T00:00:00Z",
                "allowed_actions": ["send_message"],
                "autonomous_send": True,
                "live_send": True,
                "requires_post_action_verification": True,
                "revoked_at": None,
            })
            supervisor = HostLoopSupervisor(
                argparse.Namespace(
                    data_dir=data_dir,
                    authorization=auth_path,
                    goal=None,
                    availability=None,
                    app_id="tashuo",
                    send_mode="live",
                    managed_gui_send=True,
                    harness_runtime="mac-ios-app",
                    work_dir=work_dir,
                    max_steps=1,
                    once=False,
                    json=True,
                    fixture_host=None,
                    wait_timeout=None,
                    poll_interval=1.0,
                    adapter_package=None,
                    skill_package=None,
                )
            )
            work_dir.mkdir(parents=True, exist_ok=True)
            work_item = _wechat_managed_work_item(payload_text, payload_hash)
            work_item.update({
                "work_item_id": "work_tashuo_send_sequence_expired_progress",
                "action_request_id": "act_tashuo_send_sequence_expired_progress",
                "match_id": "match_tashuo",
                "candidate_key": "tashuo_xiaoyaowan",
                "payload_format": "message_sequence",
                "payload_messages": [
                    {
                        "index": index,
                        "text": text,
                        "message_hash": hashlib.sha256(text.encode("utf-8")).hexdigest(),
                        "character_count": len(text),
                    }
                    for index, text in enumerate(messages, start=1)
                ],
                "autonomous_audit_binding": _audit_binding(
                    authorization_id="auth_tashuo_live",
                    target_match_id="match_tashuo",
                    payload_hash=payload_hash,
                ),
                "target_binding": {
                    "binding_type": "current_thread_visual_identity",
                    "target_match_id": "match_tashuo",
                    "candidate_key": "tashuo_xiaoyaowan",
                    "conversation_fingerprint": "xiaoyaowan-progress",
                    "thread_evidence": {
                        "observation_id": "obs_before",
                        "screen_state": "tashuo_conversation",
                        "latest_inbound_fingerprint": "xiaoyaowan:in",
                        "visual_anchor_hash": "old",
                    },
                },
            })
            progress_path = work_dir / "managed_sequence_progress.work_tashuo_send_sequence_expired_progress.json"
            self._write_json(progress_path, {
                "schema_version": 1,
                "work_item_id": work_item["work_item_id"],
                "action_request_id": work_item["action_request_id"],
                "payload_hash": payload_hash,
                "completed_message_count": 1,
                "sequence_started_at": "2026-06-12T00:00:00Z",
                "last_message_sent_at": "2026-06-12T00:00:00Z",
                "message_sequence_window_seconds": 60,
                "message_results": [
                    {
                        "index": 1,
                        "message_hash": hashlib.sha256(messages[0].encode("utf-8")).hexdigest(),
                        "character_count": len(messages[0]),
                        "post_action_observation_id": "gui_post_send_1",
                        "status": "ok",
                        "evidence": {"outbound_exact_text_verified": True},
                        "sent_at": "2026-06-12T00:00:00Z",
                    },
                ],
            })

            def fake_run_cli_json(*args: str, allow_error: bool = False, **kwargs: object) -> dict[str, object]:
                if len(args) >= 3 and args[0] == "harness" and args[1] == "tashuo" and "send-message" in args:
                    raise AssertionError("expired sequence must not continue sending")
                raise AssertionError(args)

            with patch.dict(os.environ, {"DATING_BOOST_NOW": "2026-06-12T00:01:01Z"}), patch.object(
                supervisor,
                "_run_cli_json",
                fake_run_cli_json,
            ):
                _write_draft_review_audit(data_dir, work_item)
                result = supervisor._handle_managed_gui_send(work_item)
            self.assertTrue(progress_path.exists())

        self.assertEqual(result["status"], "blocked")
        self.assertEqual(result["reason"], "message_sequence_window_expired")
        self.assertEqual(result["message_sequence_window_seconds"], 60)
        self.assertEqual(result["message_sequence_elapsed_seconds"], 61.0)
        self.assertEqual(result["completed_message_count"], 1)
        self.assertEqual(result["failed_message_index"], 2)
        self.assertEqual(result["next_host_action"], "observe_current_thread_and_replan_sequence")
