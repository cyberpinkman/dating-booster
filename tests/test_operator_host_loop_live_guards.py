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


class OperatorHostLoopLiveGuardTests(OperatorHostLoopTestCase):
    def test_tashuo_mac_ios_live_send_work_item_without_structural_binding_blocks(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            data_dir = root / "data"
            work_dir = root / "work"
            auth_path = root / "tashuo_auth.json"
            payload_text = "hello"
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
            work_item["target_binding"] = {"required_visible_text": ["Ada"], "target_match_id": "match_tashuo"}
            _write_draft_review_audit(data_dir, work_item)

            result = supervisor._live_send_contract_block_reason(
                work_item,
                json.loads(auth_path.read_text(encoding="utf-8")),
            )

        self.assertEqual(result, "target_binding_structural_evidence_required")

    def test_iphone_mirroring_live_send_work_item_without_structural_binding_blocks(self):
        for app_id, auth_id, match_id, candidate_key in (
            ("tinder", "auth_tinder_live", "match_tinder", "tinder_ada"),
            ("bumble", "auth_bumble_live", "match_bumble", "bumble_ada"),
        ):
            with self.subTest(app_id=app_id), tempfile.TemporaryDirectory() as temp_dir:
                root = Path(temp_dir)
                data_dir = root / "data"
                work_dir = root / "work"
                auth_path = root / f"{app_id}_auth.json"
                payload_text = "hello"
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
                work_item["target_binding"] = {"required_visible_text": ["Ada"], "target_match_id": match_id}
                _write_draft_review_audit(data_dir, work_item)

                result = supervisor._live_send_contract_block_reason(
                    work_item,
                    json.loads(auth_path.read_text(encoding="utf-8")),
                )

                self.assertEqual(result, "target_binding_structural_evidence_required")

    def test_tashuo_mac_ios_unmanaged_live_send_waits_for_action_result_after_verified_stage(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            data_dir = root / "data"
            work_dir = root / "work"
            auth_path = root / "tashuo_auth.json"
            payload_text = "hello"
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
                    managed_gui_send=False,
                    harness_runtime="mac-ios-app",
                    work_dir=work_dir,
                    max_steps=1,
                    once=False,
                    json=True,
                    fixture_host=None,
                    wait_timeout=0,
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
            staged_path = supervisor._work_file(work_item, "staged_verification")
            self._write_json(staged_path, {
                "schema_version": 1,
                "verification_type": "staged_text",
                "action_request_id": work_item["action_request_id"],
                "match_id": work_item["match_id"],
                "candidate_key": work_item["candidate_key"],
                "expected_payload_hash": payload_hash,
                "expected_payload_text": payload_text,
                "result_status": "succeeded",
                "staged_text": payload_text,
                "evidence": {"verification": "Input box text was checked before send."},
            })

            _write_draft_review_audit(data_dir, work_item)

            payload = supervisor._handle_send_message(work_item)

        self.assertEqual(payload["status"], "waiting_for_host")
        self.assertEqual(payload["stop_reason"], "waiting_for_action_result")
        self.assertEqual(payload["next_host_action"], "paste_verify_send_then_record_action_result")

    def test_tashuo_mac_ios_live_send_work_item_lost_current_thread_binding_blocks(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            data_dir = root / "data"
            work_dir = root / "work"
            auth_path = root / "tashuo_auth.json"
            payload_text = "hello"
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
            work_item.pop("target_binding")

            result = supervisor._live_send_contract_block_reason(
                work_item,
                json.loads(auth_path.read_text(encoding="utf-8")),
            )

        self.assertEqual(result, "target_binding_lost_current_thread")

    def test_blocked_send_work_item_uses_reason_specific_next_host_action(self):
        supervisor = HostLoopSupervisor(
            argparse.Namespace(
                data_dir=Path(tempfile.gettempdir()) / "dating_boost_next_action_review",
                authorization=None,
                goal=None,
                availability=None,
                app_id="tashuo",
                send_mode="live",
                managed_gui_send=True,
                harness_runtime="mac-ios-app",
                work_dir=Path(tempfile.gettempdir()) / "dating_boost_next_action_review_work",
                max_steps=1,
                once=False,
                json=True,
                fixture_host=None,
                wait_timeout=0,
                poll_interval=1.0,
                adapter_package=None,
                skill_package=None,
            )
        )
        work_item = {
            "schema_version": 1,
            "work_item_id": "work_tashuo_send",
            "work_item_type": "send_message",
            "action_request_id": "act_tashuo_send",
        }

        payload = supervisor._finish("blocked", "target_binding_structural_evidence_required", current=work_item)

        self.assertEqual(payload["next_host_action"], "provide_structural_target_binding_evidence")

    def test_once_mode_writes_template_and_waits_for_host_without_fixture(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            data_dir = Path(temp_dir) / "data"
            work_dir = Path(temp_dir) / "work"
            self._bootstrap_data_dir(data_dir)

            payload = self._run_script(
                "--data-dir",
                str(data_dir),
                "--authorization",
                str(FIXTURE_DIR / "auth.json"),
                "--goal",
                str(FIXTURE_DIR / "goal.json"),
                "--availability",
                str(FIXTURE_DIR / "availability.json"),
                "--work-dir",
                str(work_dir),
                "--initial-surface",
                "message-list",
                "--once",
                "--json",
            )

            self.assertEqual(payload["status"], "waiting_for_host")
            self.assertEqual(payload["current_work_item"]["work_item_type"], "scan_message_list")
            work_item_id = payload["current_work_item"]["work_item_id"]
            self.assertEqual(
                Path(payload["expected_input"]).resolve(),
                (work_dir / f"message_list_observation.{work_item_id}.json").resolve(),
            )
            self.assertTrue((work_dir / f"message_list_observation.{work_item_id}.template.json").exists())

    def test_supervisor_does_not_inject_fixed_clock_without_fixture_host(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            supervisor = HostLoopSupervisor(
                argparse.Namespace(
                    data_dir=Path(temp_dir) / "data",
                    authorization=None,
                    goal=None,
                    availability=None,
                    app_id="tinder",
                    send_mode="stage",
                    work_dir=Path(temp_dir) / "work",
                    max_steps=1,
                    once=False,
                    json=True,
                    fixture_host=None,
                    wait_timeout=None,
                    poll_interval=1.0,
                    skill_package=None,
                )
            )

            def fake_run(command, cwd, check, capture_output, text, env):
                self.assertNotIn("DATING_BOOST_NOW", env)
                return subprocess.CompletedProcess(command, 0, stdout='{"schema_version": 1, "status": "ok"}', stderr="")

            with patch.dict(os.environ, {}, clear=True), patch("dating_boost.host_loop.subprocess.run", fake_run):
                payload = supervisor._run_cli_json("capabilities", "--json")

        self.assertEqual(payload["status"], "ok")

    def test_supervisor_preserves_structured_cli_error_reason(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            supervisor = HostLoopSupervisor(
                argparse.Namespace(
                    data_dir=Path(temp_dir) / "data",
                    authorization=None,
                    goal=None,
                    availability=None,
                    app_id="tinder",
                    send_mode="stage",
                    work_dir=Path(temp_dir) / "work",
                    max_steps=1,
                    once=False,
                    json=True,
                    fixture_host=None,
                    wait_timeout=None,
                    poll_interval=1.0,
                    skill_package=None,
                )
            )

            def fake_run(command, cwd, check, capture_output, text, env):
                return subprocess.CompletedProcess(
                    command,
                    2,
                    stdout='{"schema_version": 1, "status": "error", "reason": "authorization_expired"}',
                    stderr="",
                )

            with patch("dating_boost.host_loop.subprocess.run", fake_run):
                with self.assertRaises(HostLoopCommandError) as raised:
                    supervisor._run_cli_json("operator", "session", "start")

        self.assertEqual(raised.exception.payload["reason"], "authorization_expired")
