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

class OperatorHostLoopTashuoVisualSequenceTests(OperatorHostLoopTestCase):
    def test_managed_tashuo_live_send_waits_for_host_visual_verification_before_return_key(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            data_dir = root / "data"
            work_dir = root / "work"
            auth_path = root / "tashuo_auth.json"
            payload_text = "那我们俩算慢热同盟了，我也是刚开始话少一点，熟了会自然很多"
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

            def fake_run_cli_json(*args: str, allow_error: bool = False, **kwargs: object) -> dict[str, object]:
                if len(args) >= 3 and args[0] == "harness" and args[1] == "tashuo" and "send-message" in args:
                    return {
                        "schema_version": 2,
                        "status": "needs_host_visual_verification",
                        "reason": "staged_text_requires_visual_verification",
                        "app_id": "tashuo",
                        "harness_backend": "mac_ios_app",
                        "action": "send_message",
                        "draft_fingerprint": payload_hash,
                        "draft_character_count": len(payload_text),
                        "staged_text_verification": {
                            "status": "needs_verification",
                            "reason": "staged_text_not_verified",
                            "expected_payload_hash": payload_hash,
                        },
                        "visual_verification_request": {
                            "schema_version": 1,
                            "verification_type": "staged_text_visual",
                            "expected_payload_hash": payload_hash,
                            "screen_path": "harness/mac_ios_app.tashuo.after_stage_message.png",
                            "input_crop_path": "harness/mac_ios_app.tashuo.after_stage_message.input_crop.png",
                            "next_host_action": "visually_verify_staged_text_before_live_send",
                        },
                    }
                if args[:2] == ("operator", "record-action-result"):
                    raise AssertionError("visual verification wait must not record a send result")
                raise AssertionError(args)

            with patch.object(supervisor, "_run_cli_json", fake_run_cli_json):
                _write_draft_review_audit(data_dir, work_item)
                result = supervisor._handle_managed_gui_send(work_item)

        self.assertEqual(result["status"], "waiting_for_host")
        self.assertEqual(result["stop_reason"], "staged_text_requires_visual_verification")
        self.assertEqual(result["next_host_action"], "visually_verify_staged_text_before_live_send")
        self.assertFalse(supervisor.action_results_recorded)
        self.assertEqual(
            result["managed_gui_send"]["visual_verification_request"]["expected_payload_hash"],
            payload_hash,
        )

    def test_managed_tashuo_live_send_waits_for_outbound_host_visual_verification(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            data_dir = root / "data"
            work_dir = root / "work"
            auth_path = root / "tashuo_auth.json"
            payload_text = "这条我居然漏到现在"
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
            work_item["candidate_key"] = "tashuo_haidian_orange"
            work_item["autonomous_audit_binding"] = _audit_binding(
                authorization_id="auth_tashuo_live",
                target_match_id="match_tashuo",
                payload_hash=payload_hash,
            )
            work_item["target_binding"] = {
                "binding_type": "current_thread_visual_identity",
                "target_match_id": "match_tashuo",
                "candidate_key": "tashuo_haidian_orange",
                "visible_name": "海淀大橙子",
                "conversation_fingerprint": "haidian-orange-latest",
                "thread_evidence": {
                    "observation_id": "obs_before",
                    "screen_state": "tashuo_conversation",
                    "latest_inbound_fingerprint": "haidian:in:latest",
                    "visual_anchor_hash": "0123456789abcdef",
                },
            }

            def fake_run_cli_json(*args: str, allow_error: bool = False, **kwargs: object) -> dict[str, object]:
                if len(args) >= 3 and args[0] == "harness" and args[1] == "tashuo" and "send-message" in args:
                    return {
                        "schema_version": 2,
                        "status": "needs_host_visual_verification",
                        "reason": "outbound_message_requires_visual_verification",
                        "app_id": "tashuo",
                        "harness_backend": "mac_ios_app",
                        "action": "send_message",
                        "draft_fingerprint": payload_hash,
                        "draft_character_count": len(payload_text),
                        "post_action_observation_id": "gui_post_send_visual_1",
                        "evidence": {
                            "staged_text_verified": True,
                            "staged_exact_text_verified": True,
                            "staged_exact_text_ax_verified": True,
                            "staged_exact_text_ocr_verified": False,
                            "input_cleared_after_send": True,
                            "post_action_screen_captured": True,
                            "outbound_message_verified": False,
                            "outbound_exact_text_verified": False,
                            "outbound_exact_text_ax_verified": False,
                            "outbound_exact_text_ocr_verified": False,
                        },
                        "visual_verification_request": {
                            "schema_version": 1,
                            "verification_type": "outbound_message_visual",
                            "expected_payload_hash": payload_hash,
                            "post_screen_path": "harness/mac_ios_app.tashuo.after_send_message.png",
                            "post_action_observation_id": "gui_post_send_visual_1",
                            "ocr_status": "skipped",
                            "next_host_action": "visually_verify_outbound_message_after_live_send",
                        },
                    }
                if args[:2] == ("operator", "record-action-result"):
                    raise AssertionError("outbound visual wait must not record until host writes action_result")
                raise AssertionError(args)

            with patch.object(supervisor, "_run_cli_json", fake_run_cli_json):
                _write_draft_review_audit(data_dir, work_item)
                result = supervisor._handle_managed_gui_send(work_item)

        self.assertEqual(result["status"], "waiting_for_host")
        self.assertEqual(result["stop_reason"], "outbound_message_requires_visual_verification")
        self.assertEqual(result["next_host_action"], "visually_verify_outbound_message_after_live_send_and_write_action_result")
        self.assertEqual(Path(result["expected_input"]).name, f"action_result.{work_item['work_item_id']}.json")
        self.assertEqual(result["managed_gui_send"]["visual_verification_request"]["ocr_status"], "skipped")
        self.assertFalse(supervisor.action_results_recorded)

    def test_managed_tashuo_sequence_outbound_visual_wait_saves_pending_progress(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            data_dir = root / "data"
            work_dir = root / "work"
            auth_path = root / "tashuo_auth.json"
            messages = ["第一句", "第二句"]
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
                "work_item_id": "work_tashuo_sequence_visual_wait",
                "action_request_id": "act_tashuo_sequence_visual_wait",
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
                    "conversation_fingerprint": "duoduo-sequence",
                    "thread_evidence": {
                        "observation_id": "obs_before",
                        "screen_state": "tashuo_conversation",
                        "latest_inbound_fingerprint": "duoduo:in",
                        "visual_anchor_hash": "old",
                    },
                },
            })

            def fake_run_cli_json(*args: str, allow_error: bool = False, **kwargs: object) -> dict[str, object]:
                if len(args) >= 3 and args[0] == "harness" and args[1] == "tashuo" and "send-message" in args:
                    text_path = Path(args[args.index("--text-file") + 1])
                    self.assertEqual(text_path.read_text(encoding="utf-8"), "第一句")
                    return {
                        "schema_version": 2,
                        "status": "needs_host_visual_verification",
                        "reason": "outbound_message_requires_visual_verification",
                        "post_action_observation_id": "gui_post_send_1",
                        "evidence": {
                            "staged_text_verified": True,
                            "staged_exact_text_verified": True,
                            "input_cleared_after_send": True,
                            "post_action_screen_captured": True,
                            "outbound_message_verified": False,
                            "outbound_exact_text_verified": False,
                        },
                        "visual_verification_request": {
                            "schema_version": 1,
                            "verification_type": "outbound_message_visual",
                            "expected_payload_hash": hashlib.sha256("第一句".encode("utf-8")).hexdigest(),
                            "post_action_observation_id": "gui_post_send_1",
                            "ocr_status": "skipped",
                        },
                        "current_thread_visual_anchor": {
                            "status": "ok",
                            "screen_state": "tashuo_conversation",
                            "visual_anchor_hash": "fresh-after-first",
                        },
                    }
                raise AssertionError(args)

            with patch.dict(os.environ, {"DATING_BOOST_NOW": "2026-06-12T00:00:00Z"}), patch.object(
                supervisor,
                "_run_cli_json",
                fake_run_cli_json,
            ):
                _write_draft_review_audit(data_dir, work_item)
                result = supervisor._handle_managed_gui_send(work_item)

            progress_path = work_dir / "managed_sequence_progress.work_tashuo_sequence_visual_wait.json"
            progress = json.loads(progress_path.read_text(encoding="utf-8"))

        self.assertEqual(result["status"], "waiting_for_host")
        self.assertEqual(result["stop_reason"], "outbound_message_requires_visual_verification")
        self.assertEqual(result["next_host_action"], "visually_verify_sequence_outbound_message_and_resume")
        self.assertEqual(Path(result["expected_input"]).name, "managed_sequence_visual_verification.work_tashuo_sequence_visual_wait.01.json")
        self.assertEqual(progress["completed_message_count"], 0)
        self.assertEqual(progress["sequence_started_at"], "2026-06-12T00:00:00Z")
        self.assertEqual(progress["last_message_sent_at"], "2026-06-12T00:00:00Z")
        self.assertEqual(progress["target_binding"]["thread_evidence"]["visual_anchor_hash"], "fresh-after-first")
        self.assertEqual(progress["message_results"][0]["status"], "visual_verification_pending")
        self.assertEqual(progress["message_results"][0]["post_action_observation_id"], "gui_post_send_1")
        self.assertTrue(progress["message_results"][0]["evidence"]["input_cleared_after_send"])
        self.assertFalse(supervisor.action_results_recorded)

    def test_managed_tashuo_sequence_visual_confirmation_resumes_without_resending_pending_message(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            data_dir = root / "data"
            work_dir = root / "work"
            auth_path = root / "tashuo_auth.json"
            messages = ["第一句", "第二句"]
            payload_text = "\n".join(messages)
            payload_hash = hashlib.sha256(
                json.dumps(
                    {"payload_format": "message_sequence", "messages": messages},
                    ensure_ascii=False,
                    sort_keys=True,
                    separators=(",", ":"),
                ).encode("utf-8")
            ).hexdigest()
            message_hashes = [hashlib.sha256(text.encode("utf-8")).hexdigest() for text in messages]
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
                "work_item_id": "work_tashuo_sequence_visual_resume",
                "action_request_id": "act_tashuo_sequence_visual_resume",
                "match_id": "match_tashuo",
                "candidate_key": "tashuo_duoduo",
                "payload_format": "message_sequence",
                "payload_messages": [
                    {
                        "index": index,
                        "text": text,
                        "message_hash": message_hashes[index - 1],
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
                    "conversation_fingerprint": "duoduo-sequence",
                    "thread_evidence": {
                        "observation_id": "obs_before",
                        "screen_state": "tashuo_conversation",
                        "latest_inbound_fingerprint": "duoduo:in",
                        "visual_anchor_hash": "old",
                    },
                },
            })
            progress_path = work_dir / "managed_sequence_progress.work_tashuo_sequence_visual_resume.json"
            self._write_json(progress_path, {
                "schema_version": 1,
                "work_item_id": work_item["work_item_id"],
                "action_request_id": work_item["action_request_id"],
                "payload_hash": payload_hash,
                "completed_message_count": 0,
                "sequence_started_at": "2026-06-12T00:00:00Z",
                "last_message_sent_at": "2026-06-12T00:00:00Z",
                "message_sequence_window_seconds": 40,
                "target_binding": {
                    "binding_type": "current_thread_visual_identity",
                    "target_match_id": "match_tashuo",
                    "candidate_key": "tashuo_duoduo",
                    "conversation_fingerprint": "duoduo-sequence",
                    "thread_evidence": {
                        "observation_id": "gui_post_send_1",
                        "screen_state": "tashuo_conversation",
                        "latest_inbound_fingerprint": "duoduo:in",
                        "visual_anchor_hash": "fresh-after-first",
                    },
                },
                "message_results": [
                    {
                        "index": 1,
                        "message_hash": message_hashes[0],
                        "character_count": len(messages[0]),
                        "post_action_observation_id": "gui_post_send_1",
                        "status": "visual_verification_pending",
                        "sent_at": "2026-06-12T00:00:00Z",
                        "evidence": {
                            "staged_text_verified": True,
                            "staged_exact_text_verified": True,
                            "input_cleared_after_send": True,
                            "post_action_screen_captured": True,
                            "outbound_message_verified": False,
                            "outbound_exact_text_verified": False,
                        },
                    },
                ],
            })
            visual_path = work_dir / "managed_sequence_visual_verification.work_tashuo_sequence_visual_resume.01.json"
            self._write_json(visual_path, {
                "schema_version": 1,
                "action_request_id": work_item["action_request_id"],
                "payload_hash": payload_hash,
                "message_index": 1,
                "message_hash": message_hashes[0],
                "post_action_observation_id": "gui_post_send_1",
                "result_status": "succeeded",
                "post_send_visible_text": "第一句",
                "evidence": {
                    "host_visual_outbound_exact_text_verified": True,
                    "input_cleared_after_send": True,
                    "post_action_screen_captured": True,
                },
            })
            sent_texts: list[str] = []
            recorded_result: dict[str, object] = {}

            def fake_run_cli_json(*args: str, allow_error: bool = False, **kwargs: object) -> dict[str, object]:
                if len(args) >= 3 and args[0] == "harness" and args[1] == "tashuo" and "send-message" in args:
                    text_path = Path(args[args.index("--text-file") + 1])
                    sent_texts.append(text_path.read_text(encoding="utf-8"))
                    return {
                        "schema_version": 2,
                        "status": "ok",
                        "post_action_observation_id": "gui_post_send_2",
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

            with patch.dict(os.environ, {"DATING_BOOST_NOW": "2026-06-12T00:00:10Z"}), patch.object(
                supervisor,
                "_run_cli_json",
                fake_run_cli_json,
            ):
                _write_draft_review_audit(data_dir, work_item)
                result = supervisor._handle_managed_gui_send(work_item)

        self.assertIsNone(result)
        self.assertEqual(sent_texts, ["第二句"])
        self.assertEqual(recorded_result["message_count"], 2)
        self.assertEqual(recorded_result["post_action_observation_id"], "gui_post_send_2")
        self.assertEqual(recorded_result["message_results"][0]["status"], "ok")
        self.assertTrue(recorded_result["message_results"][0]["evidence"]["outbound_exact_text_verified"])
        self.assertEqual(recorded_result["message_results"][1]["status"], "ok")
        self.assertFalse(progress_path.exists())
        self.assertFalse(visual_path.exists())

    def test_managed_tashuo_resume_records_visual_action_result_without_resending(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            data_dir = root / "data"
            work_dir = root / "work"
            auth_path = root / "tashuo_auth.json"
            payload_text = "这条我居然漏到现在"
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
            work_item["candidate_key"] = "tashuo_haidian_orange"
            work_item["autonomous_audit_binding"] = _audit_binding(
                authorization_id="auth_tashuo_live",
                target_match_id="match_tashuo",
                payload_hash=payload_hash,
            )
            work_item["target_binding"] = {
                "binding_type": "current_thread_visual_identity",
                "target_match_id": "match_tashuo",
                "candidate_key": "tashuo_haidian_orange",
                "visible_name": "海淀大橙子",
                "conversation_fingerprint": "haidian-orange-latest",
                "thread_evidence": {
                    "observation_id": "obs_before",
                    "screen_state": "tashuo_conversation",
                    "latest_inbound_fingerprint": "haidian:in:latest",
                    "visual_anchor_hash": "0123456789abcdef",
                },
            }
            result_path = work_dir / f"action_result.{work_item['work_item_id']}.json"
            self._write_json(result_path, {
                "action_request_id": work_item["action_request_id"],
                "action": "send_message",
                "target_match_id": "match_tashuo",
                "payload_hash": payload_hash,
                "precondition_hash": work_item.get("precondition_hash"),
                "autonomous_audit_binding": work_item.get("autonomous_audit_binding"),
                "pre_action_observation_id": work_item.get("pre_action_observation_id"),
                "post_action_observation_id": "gui_post_send_visual_1",
                "result_status": "succeeded",
                "evidence": {
                    "managed_gui_send": True,
                    "host_visual_outbound_exact_text_verified": True,
                    "ocr_status": "skipped",
                    "input_cleared_after_send": True,
                    "post_action_screen_captured": True,
                },
            })
            recorded_result: dict[str, object] = {}

            def fake_run_cli_json(*args: str, allow_error: bool = False, **kwargs: object) -> dict[str, object]:
                if len(args) >= 3 and args[0] == "harness" and args[1] == "tashuo" and "send-message" in args:
                    raise AssertionError("resume with action_result must not call harness send-message again")
                if args[:2] == ("operator", "record-action-result"):
                    recorded_path = Path(args[args.index("--input") + 1])
                    recorded_result.update(json.loads(recorded_path.read_text(encoding="utf-8")))
                    return {"schema_version": 1, "status": "ok", "recorded": True}
                raise AssertionError(args)

            with patch.object(supervisor, "_run_cli_json", fake_run_cli_json):
                _write_draft_review_audit(data_dir, work_item)
                result = supervisor._handle_managed_gui_send(work_item)

        self.assertIsNone(result)
        self.assertEqual(recorded_result["result_status"], "succeeded")
        self.assertEqual(recorded_result["post_action_observation_id"], "gui_post_send_visual_1")
        self.assertTrue(supervisor.action_results_recorded)
