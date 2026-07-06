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


class OperatorHostLoopManagedSendTests(OperatorHostLoopTestCase):
    def test_managed_wechat_live_send_runs_harness_with_text_file_and_records_result(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            data_dir = root / "data"
            work_dir = root / "work"
            auth_path = root / "wechat_auth.json"
            payload_text = "今晚可以聊十分钟吗？"
            payload_hash = hashlib.sha256(payload_text.encode("utf-8")).hexdigest()
            self._write_json(auth_path, {
                "schema_version": 1,
                "authorization_id": "auth_wechat_live",
                "scope": "send_chat_messages",
                "app_id": "wechat",
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
                    app_id="wechat",
                    send_mode="live",
                    managed_gui_send=True,
                    work_dir=work_dir,
                    max_steps=1,
                    once=False,
                    json=True,
                    fixture_host=None,
                    wait_timeout=None,
                    poll_interval=1.0,
                    skill_package=None,
                )
            )
            work_dir.mkdir(parents=True, exist_ok=True)
            work_item = {
                "schema_version": 1,
                "work_item_id": "work_wechat_send",
                "work_item_type": "send_message",
                "action_request_id": "act_wechat_send",
                "match_id": "match_wechat",
                "candidate_key": "wechat_ada",
                "payload_text": payload_text,
                "payload_hash": payload_hash,
                "precondition_hash": "pre_hash",
                "autonomous_audit_binding": _audit_binding(
                    authorization_id="auth_wechat_live",
                    target_match_id="match_wechat",
                    payload_hash=payload_hash,
                ),
                "pre_action_observation_id": "obs_before",
                "draft_review_id": "draft_review_fixture",
                "draft_evidence_id": "draft_evidence_fixture",
                "draft_generation_id": "draft_generation_fixture",
                "latest_turn_id": "latest_turn_fixture",
                "conversation_thread_revision": 1,
                "draft_self_review_summary": {
                    "schema_version": 1,
                    "status": "ok",
                    "ai_or_weird_probability": 20,
                    "attempts": 1,
                    "source": "unit_fixture",
                },
                "policy": {"allowed": True, "draft_review_id": "draft_review_fixture"},
                "planner_alignment": "ok",
                "conversation_stage": "rapport_building",
                "conversation_move": "warm_reciprocal_question",
                "target_profile_observation": {
                    "review_status": "observed",
                    "profile_text": "喜欢日料，周末常去看展。",
                    "photo_cues": [],
                    "hook_candidates": ["日料", "看展"],
                    "evidence": "Profile was reviewed before drafting.",
                },
                "requires_post_action_verification": True,
                "target_binding": {"required_visible_text": ["Ada"], "target_match_id": "match_wechat"},
            }
            captured_commands: list[tuple[str, ...]] = []
            recorded_result: dict[str, object] = {}

            def fake_run_cli_json(*args: str, allow_error: bool = False, **kwargs: object) -> dict[str, object]:
                captured_commands.append(args)
                if args[:3] == ("harness", "wechat", "send-message"):
                    self.assertIn("--text-file", args)
                    self.assertIn("--action-request", args)
                    self.assertNotIn(payload_text, args)
                    text_path = Path(args[args.index("--text-file") + 1])
                    action_path = Path(args[args.index("--action-request") + 1])
                    self.assertEqual(text_path.read_text(encoding="utf-8"), payload_text)
                    action_request = json.loads(action_path.read_text(encoding="utf-8"))
                    self.assertEqual(action_request["payload_hash"], payload_hash)
                    self.assertEqual(action_request["target_binding"]["required_visible_text"], ["Ada"])
                    return {
                        "schema_version": 1,
                        "status": "ok",
                        "app_id": "wechat",
                        "action": "send_message",
                        "draft_fingerprint": payload_hash,
                        "draft_character_count": len(payload_text),
                        "post_action_observation_id": "gui_post_send_1234",
                        "evidence": {
                            "staged_text_verified": True,
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

            with patch.dict(os.environ, {"DATING_BOOST_NOW": "2026-06-12T00:00:00Z"}), patch.object(supervisor, "_run_cli_json", fake_run_cli_json):
                _write_draft_review_audit(data_dir, work_item)
                result = supervisor._handle_managed_gui_send(work_item)

        self.assertIsNone(result)
        self.assertEqual(recorded_result["result_status"], "succeeded")
        self.assertEqual(recorded_result["post_action_observation_id"], "gui_post_send_1234")
        self.assertTrue(recorded_result["evidence"]["managed_gui_send"])
        self.assertTrue(supervisor.staged_verifications)
        self.assertTrue(supervisor.action_results_recorded)
        self.assertFalse(any(path.name.startswith("managed_payload.") for path in work_dir.glob("*.txt")))
        self.assertFalse(any(path.name.startswith("managed_action_request.") for path in work_dir.glob("*.json")))
        self.assertTrue(any(args[:3] == ("harness", "wechat", "send-message") for args in captured_commands))

    def test_managed_wechat_live_send_sends_message_sequence_as_separate_harness_calls(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            data_dir = root / "data"
            work_dir = root / "work"
            auth_path = root / "wechat_auth.json"
            messages = [
                "慢热联盟可以成立",
                "狼人杀这种局我一般也先观察一会儿",
                "熟了再开麦会比较自然",
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
                "authorization_id": "auth_wechat_live",
                "scope": "send_chat_messages",
                "app_id": "wechat",
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
                    app_id="wechat",
                    send_mode="live",
                    managed_gui_send=True,
                    work_dir=work_dir,
                    max_steps=1,
                    once=False,
                    json=True,
                    fixture_host=None,
                    wait_timeout=None,
                    poll_interval=1.0,
                    skill_package=None,
                )
            )
            work_dir.mkdir(parents=True, exist_ok=True)
            work_item = {
                "schema_version": 1,
                "work_item_id": "work_wechat_send_sequence",
                "work_item_type": "send_message",
                "action_request_id": "act_wechat_send_sequence",
                "match_id": "match_wechat",
                "candidate_key": "wechat_ada",
                "payload_text": payload_text,
                "payload_hash": payload_hash,
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
                "precondition_hash": "pre_hash",
                "autonomous_audit_binding": _audit_binding(
                    authorization_id="auth_wechat_live",
                    target_match_id="match_wechat",
                    payload_hash=payload_hash,
                ),
                "pre_action_observation_id": "obs_before",
                "draft_review_id": "draft_review_fixture",
                "draft_evidence_id": "draft_evidence_fixture",
                "draft_generation_id": "draft_generation_fixture",
                "latest_turn_id": "latest_turn_fixture",
                "conversation_thread_revision": 1,
                "draft_self_review_summary": {
                    "schema_version": 1,
                    "status": "ok",
                    "ai_or_weird_probability": 20,
                    "attempts": 1,
                    "source": "unit_fixture",
                },
                "policy": {"allowed": True, "draft_review_id": "draft_review_fixture"},
                "planner_alignment": "ok",
                "conversation_stage": "warmup",
                "conversation_move": "low_investment_repair",
                "target_profile_observation": {
                    "review_status": "observed",
                    "profile_text": "喜欢狼人杀。",
                    "photo_cues": [],
                    "hook_candidates": ["狼人杀"],
                    "evidence": "Profile was reviewed before drafting.",
                },
                "requires_post_action_verification": True,
                "target_binding": {"required_visible_text": ["Ada"], "target_match_id": "match_wechat"},
            }
            sent_texts: list[str] = []
            recorded_result: dict[str, object] = {}

            def fake_run_cli_json(*args: str, allow_error: bool = False, **kwargs: object) -> dict[str, object]:
                if args[:3] == ("harness", "wechat", "send-message"):
                    text_path = Path(args[args.index("--text-file") + 1])
                    action_path = Path(args[args.index("--action-request") + 1])
                    message_text = text_path.read_text(encoding="utf-8")
                    sent_texts.append(message_text)
                    action_request = json.loads(action_path.read_text(encoding="utf-8"))
                    self.assertEqual(action_request["payload_text"], message_text)
                    self.assertEqual(action_request["payload_hash"], hashlib.sha256(message_text.encode("utf-8")).hexdigest())
                    self.assertNotEqual(action_request["payload_hash"], payload_hash)
                    return {
                        "schema_version": 1,
                        "status": "ok",
                        "app_id": "wechat",
                        "action": "send_message",
                        "draft_fingerprint": action_request["payload_hash"],
                        "draft_character_count": len(message_text),
                        "post_action_observation_id": f"gui_post_send_{len(sent_texts)}",
                        "evidence": {
                            "staged_text_verified": True,
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
        self.assertEqual(recorded_result["post_action_observation_id"], "gui_post_send_3")

    def test_managed_wechat_live_send_derives_target_binding_from_pending_thread_observation(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            data_dir = root / "data"
            work_dir = root / "work"
            auth_path = root / "wechat_auth.json"
            payload_text = "今晚可以聊十分钟吗？"
            payload_hash = hashlib.sha256(payload_text.encode("utf-8")).hexdigest()
            self._write_json(auth_path, {
                "schema_version": 1,
                "authorization_id": "auth_wechat_live",
                "scope": "send_chat_messages",
                "app_id": "wechat",
                "expires_at": "2099-01-01T00:00:00Z",
                "allowed_actions": ["send_message"],
                "autonomous_send": True,
                "live_send": True,
                "requires_post_action_verification": True,
                "revoked_at": None,
            })
            (data_dir / "operator").mkdir(parents=True, exist_ok=True)
            self._write_json(data_dir / "operator" / "pending_scan_batch.json", {
                "schema_version": 1,
                "session_id": "session_wechat",
                "app_id": "wechat",
                "thread_observations": [
                    {
                        "candidate_key": "wechat_ada",
                        "observation": {
                            "match_identity_hints": {
                                "visible_name": "Ada",
                                "conversation_fingerprint": "Ada latest dinner thread",
                            }
                        },
                    }
                ],
            })
            supervisor = HostLoopSupervisor(
                argparse.Namespace(
                    data_dir=data_dir,
                    authorization=auth_path,
                    goal=None,
                    availability=None,
                    app_id="wechat",
                    send_mode="live",
                    managed_gui_send=True,
                    work_dir=work_dir,
                    max_steps=1,
                    once=False,
                    json=True,
                    fixture_host=None,
                    wait_timeout=None,
                    poll_interval=1.0,
                    skill_package=None,
                )
            )
            work_dir.mkdir(parents=True, exist_ok=True)
            work_item = _wechat_managed_work_item(payload_text, payload_hash)
            work_item.pop("target_binding")
            observed_binding: dict[str, object] = {}

            def fake_run_cli_json(*args: str, allow_error: bool = False, **kwargs: object) -> dict[str, object]:
                if args[:3] == ("harness", "wechat", "send-message"):
                    action_path = Path(args[args.index("--action-request") + 1])
                    action_request = json.loads(action_path.read_text(encoding="utf-8"))
                    observed_binding.update(action_request["target_binding"])
                    return {
                        "schema_version": 1,
                        "status": "ok",
                        "app_id": "wechat",
                        "action": "send_message",
                        "post_action_observation_id": "gui_post_send_1234",
                        "evidence": {
                            "staged_text_verified": True,
                            "staged_exact_text_ocr_verified": True,
                            "input_cleared_after_send": True,
                            "post_action_screen_captured": True,
                            "outbound_message_verified": True,
                            "outbound_exact_text_ocr_verified": True,
                        },
                    }
                if args[:2] == ("operator", "record-action-result"):
                    return {"schema_version": 1, "status": "ok", "recorded": True}
                raise AssertionError(args)

            with patch.object(supervisor, "_run_cli_json", fake_run_cli_json):
                _write_draft_review_audit(data_dir, work_item)
                result = supervisor._handle_managed_gui_send(work_item)

        self.assertIsNone(result)
        self.assertEqual(observed_binding["target_match_id"], "match_wechat")
        self.assertEqual(observed_binding["candidate_key"], "wechat_ada")
        self.assertEqual(observed_binding["visible_name"], "Ada")
        self.assertEqual(observed_binding["required_visible_text"], ["Ada"])
        self.assertEqual(observed_binding["conversation_fingerprint"], "Ada latest dinner thread")

    def test_managed_wechat_live_send_blocks_when_outbound_evidence_is_missing(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            data_dir = root / "data"
            work_dir = root / "work"
            auth_path = root / "wechat_auth.json"
            payload_text = "今晚可以聊十分钟吗？"
            payload_hash = hashlib.sha256(payload_text.encode("utf-8")).hexdigest()
            self._write_json(auth_path, {
                "schema_version": 1,
                "authorization_id": "auth_wechat_live",
                "scope": "send_chat_messages",
                "app_id": "wechat",
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
                    app_id="wechat",
                    send_mode="live",
                    managed_gui_send=True,
                    work_dir=work_dir,
                    max_steps=1,
                    once=False,
                    json=True,
                    fixture_host=None,
                    wait_timeout=None,
                    poll_interval=1.0,
                    skill_package=None,
                )
            )
            work_dir.mkdir(parents=True, exist_ok=True)
            work_item = _wechat_managed_work_item(payload_text, payload_hash)

            def fake_run_cli_json(*args: str, allow_error: bool = False, **kwargs: object) -> dict[str, object]:
                if args[:3] == ("harness", "wechat", "send-message"):
                    return {
                        "schema_version": 1,
                        "status": "ok",
                        "app_id": "wechat",
                        "action": "send_message",
                        "post_action_observation_id": "gui_post_send_1234",
                        "evidence": {
                            "staged_text_verified": True,
                            "input_cleared_after_send": True,
                            "post_action_screen_captured": True,
                        },
                    }
                raise AssertionError(args)

            with patch.object(supervisor, "_run_cli_json", fake_run_cli_json):
                _write_draft_review_audit(data_dir, work_item)
                result = supervisor._handle_managed_gui_send(work_item)

        self.assertEqual(result["status"], "blocked")
        self.assertEqual(result["stop_reason"], "managed_gui_send_verification_incomplete")
        self.assertFalse(supervisor.action_results_recorded)

    def test_managed_live_send_blocks_when_target_profile_was_not_observed(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            data_dir = root / "data"
            work_dir = root / "work"
            auth_path = root / "wechat_auth.json"
            payload_text = "今晚可以聊十分钟吗？"
            payload_hash = hashlib.sha256(payload_text.encode("utf-8")).hexdigest()
            self._write_json(auth_path, {
                "schema_version": 1,
                "authorization_id": "auth_wechat_live",
                "scope": "send_chat_messages",
                "app_id": "wechat",
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
                    app_id="wechat",
                    send_mode="live",
                    managed_gui_send=True,
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
            work_item["target_profile_observation"] = {
                "review_status": "missing",
                "profile_text": "",
                "photo_cues": [],
                "hook_candidates": [],
                "evidence": "Profile has not been opened.",
            }

            def fake_run_cli_json(*args: str, allow_error: bool = False, **kwargs: object) -> dict[str, object]:
                if len(args) >= 3 and args[0] == "harness" and "send-message" in args:
                    raise AssertionError("target profile gate must block before harness send")
                if args[:2] == ("operator", "record-action-result"):
                    raise AssertionError("target profile gate must not record an action result")
                raise AssertionError(args)

            with patch.object(supervisor, "_run_cli_json", fake_run_cli_json):
                _write_draft_review_audit(data_dir, work_item)
                result = supervisor._handle_managed_gui_send(work_item)

        self.assertEqual(result["status"], "blocked")
        self.assertEqual(result["stop_reason"], "target_profile_required")
        self.assertEqual(result["next_host_action"], "open_target_profile_and_ingest_memory")
        self.assertEqual(result["action_results_recorded"], [])

    def test_managed_tinder_live_send_records_required_iphone_mirroring_evidence(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            data_dir = root / "data"
            work_dir = root / "work"
            auth_path = root / "tinder_auth.json"
            payload_text = "今晚可以聊十分钟吗？"
            payload_hash = hashlib.sha256(payload_text.encode("utf-8")).hexdigest()
            self._write_json(auth_path, {
                "schema_version": 1,
                "authorization_id": "auth_tinder_live",
                "scope": "send_chat_messages",
                "app_id": "tinder",
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
                    app_id="tinder",
                    send_mode="live",
                    managed_gui_send=True,
                    work_dir=work_dir,
                    max_steps=1,
                    once=False,
                    json=True,
                    fixture_host=None,
                    wait_timeout=None,
                    poll_interval=1.0,
                    skill_package=None,
                )
            )
            work_dir.mkdir(parents=True, exist_ok=True)
            work_item = _wechat_managed_work_item(payload_text, payload_hash)
            work_item["match_id"] = "match_tinder"
            work_item["candidate_key"] = "tinder_ada"
            work_item["autonomous_audit_binding"] = _audit_binding(
                authorization_id="auth_tinder_live",
                target_match_id="match_tinder",
                payload_hash=payload_hash,
            )
            work_item["target_binding"] = _iphone_current_thread_target_binding(
                "tinder",
                "match_tinder",
                "tinder_ada",
            )
            recorded_result: dict[str, object] = {}

            def fake_run_cli_json(*args: str, allow_error: bool = False, **kwargs: object) -> dict[str, object]:
                if args[:3] == ("harness", "tinder", "send-message"):
                    self.assertIn("--action-request", args)
                    action_path = Path(args[args.index("--action-request") + 1])
                    action_request = json.loads(action_path.read_text(encoding="utf-8"))
                    self.assertEqual(action_request["target_binding"]["binding_type"], "current_thread_visual_identity")
                    self.assertEqual(action_request["target_binding"]["thread_evidence"]["screen_state"], "tinder_conversation")
                    return {
                        "schema_version": 1,
                        "status": "ok",
                        "app_id": "tinder",
                        "action": "send_message",
                        "post_action_observation_id": "gui_post_send_tinder_1234",
                        "evidence": {
                            "staged_text_verified": True,
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
        self.assertEqual(recorded_result["post_action_observation_id"], "gui_post_send_tinder_1234")
        self.assertTrue(recorded_result["evidence"]["managed_gui_send"])
        self.assertTrue(recorded_result["evidence"]["staged_exact_text_verified"])
        self.assertTrue(recorded_result["evidence"]["input_cleared_after_send"])
        self.assertTrue(recorded_result["evidence"]["outbound_message_verified"])
        self.assertTrue(recorded_result["evidence"]["outbound_exact_text_verified"])

    def test_managed_iphone_mirroring_live_send_waits_for_staged_host_visual_verification(self):
        for app_id, auth_id, match_id, candidate_key in (
            ("tinder", "auth_tinder_live", "match_tinder", "tinder_ada"),
            ("bumble", "auth_bumble_live", "match_bumble", "bumble_ada"),
        ):
            with self.subTest(app_id=app_id), tempfile.TemporaryDirectory() as temp_dir:
                root = Path(temp_dir)
                data_dir = root / "data"
                work_dir = root / "work"
                auth_path = root / f"{app_id}_auth.json"
                payload_text = "hi"
                payload_hash = hashlib.sha256(payload_text.encode("utf-8")).hexdigest()
                self._write_json(auth_path, {
                    "schema_version": 1,
                    "authorization_id": auth_id,
                    "scope": "send_chat_messages",
                    "app_id": app_id,
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
                        app_id=app_id,
                        send_mode="live",
                        managed_gui_send=True,
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
                work_item["match_id"] = match_id
                work_item["candidate_key"] = candidate_key
                work_item["autonomous_audit_binding"] = _audit_binding(
                    authorization_id=auth_id,
                    target_match_id=match_id,
                    payload_hash=payload_hash,
                )
                work_item["target_binding"] = _iphone_current_thread_target_binding(app_id, match_id, candidate_key)

                def fake_run_cli_json(*args: str, allow_error: bool = False, **kwargs: object) -> dict[str, object]:
                    if args[:3] == ("harness", app_id, "send-message"):
                        return {
                            "schema_version": 1,
                            "status": "needs_host_visual_verification",
                            "reason": "staged_text_requires_visual_verification",
                            "app_id": app_id,
                            "action": "send_message",
                            "draft_fingerprint": payload_hash,
                            "draft_character_count": len(payload_text),
                            "visual_verification_request": {
                                "schema_version": 1,
                                "verification_type": "staged_text_visual",
                                "expected_payload_hash": payload_hash,
                                "screen_path": f"harness/iphone_mirroring.{app_id}.after_stage_message.png",
                                "next_host_action": "visually_verify_staged_text_before_live_send",
                            },
                        }
                    if args[:2] == ("operator", "record-action-result"):
                        raise AssertionError("staged visual wait must not record a send result")
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

    def test_managed_bumble_live_send_runs_bumble_harness_and_records_result(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            data_dir = root / "data"
            work_dir = root / "work"
            auth_path = root / "bumble_auth.json"
            payload_text = "今晚可以聊十分钟吗？"
            payload_hash = hashlib.sha256(payload_text.encode("utf-8")).hexdigest()
            self._write_json(auth_path, {
                "schema_version": 1,
                "authorization_id": "auth_bumble_live",
                "scope": "send_chat_messages",
                "app_id": "bumble",
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
                    app_id="bumble",
                    send_mode="live",
                    managed_gui_send=True,
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
            work_item["match_id"] = "match_bumble"
            work_item["candidate_key"] = "bumble_ada"
            work_item["autonomous_audit_binding"] = _audit_binding(
                authorization_id="auth_bumble_live",
                target_match_id="match_bumble",
                payload_hash=payload_hash,
            )
            work_item["target_binding"] = _iphone_current_thread_target_binding(
                "bumble",
                "match_bumble",
                "bumble_ada",
            )
            recorded_result: dict[str, object] = {}

            def fake_run_cli_json(*args: str, allow_error: bool = False, **kwargs: object) -> dict[str, object]:
                if args[:3] == ("harness", "bumble", "send-message"):
                    self.assertIn("--action-request", args)
                    action_path = Path(args[args.index("--action-request") + 1])
                    action_request = json.loads(action_path.read_text(encoding="utf-8"))
                    self.assertEqual(action_request["app_id"], "bumble")
                    self.assertEqual(action_request["target_binding"]["binding_type"], "current_thread_visual_identity")
                    self.assertEqual(action_request["target_binding"]["thread_evidence"]["screen_state"], "bumble_conversation")
                    return {
                        "schema_version": 1,
                        "status": "ok",
                        "app_id": "bumble",
                        "action": "send_message",
                        "post_action_observation_id": "gui_post_send_bumble_1234",
                        "evidence": {
                            "staged_text_verified": True,
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
        self.assertEqual(recorded_result["post_action_observation_id"], "gui_post_send_bumble_1234")
        self.assertTrue(recorded_result["evidence"]["managed_gui_send"])
        self.assertTrue(recorded_result["evidence"]["outbound_message_verified"])
