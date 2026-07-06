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


class OperatorHostLoopIphoneSequenceTests(OperatorHostLoopTestCase):
    def test_managed_iphone_mirroring_sequence_refreshes_target_binding_visual_anchor(self):
        for app_id, auth_id, match_id, candidate_key in (
            ("tinder", "auth_tinder_live", "match_tinder", "tinder_ada"),
            ("bumble", "auth_bumble_live", "match_bumble", "bumble_ada"),
        ):
            with self.subTest(app_id=app_id), tempfile.TemporaryDirectory() as temp_dir:
                root = Path(temp_dir)
                data_dir = root / "data"
                work_dir = root / "work"
                auth_path = root / f"{app_id}_auth.json"
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
                work_item.update({
                    "work_item_id": f"work_{app_id}_send_sequence",
                    "action_request_id": f"act_{app_id}_send_sequence",
                    "match_id": match_id,
                    "candidate_key": candidate_key,
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
                        authorization_id=auth_id,
                        target_match_id=match_id,
                        payload_hash=payload_hash,
                    ),
                    "target_binding": _iphone_current_thread_target_binding(app_id, match_id, candidate_key),
                })
                calls: list[str] = []
                second_action_request: dict[str, object] = {}
                recorded_result: dict[str, object] = {}

                def fake_run_cli_json(*args: str, allow_error: bool = False, **kwargs: object) -> dict[str, object]:
                    if len(args) >= 3 and args[0] == "harness" and args[1] == app_id and "send-message" in args:
                        text_path = Path(args[args.index("--text-file") + 1])
                        action_path = Path(args[args.index("--action-request") + 1])
                        calls.append(text_path.read_text(encoding="utf-8"))
                        action_request = json.loads(action_path.read_text(encoding="utf-8"))
                        if len(calls) == 2:
                            second_action_request.update(action_request)
                        return {
                            "schema_version": 2,
                            "status": "ok",
                            "app_id": app_id,
                            "action": "send_message",
                            "post_action_observation_id": f"gui_post_send_{app_id}_{len(calls)}",
                            "current_thread_visual_anchor": {
                                "status": "ok",
                                "screen_state": f"{app_id}_conversation",
                                "visual_anchor_hash": f"fresh-{app_id}-{len(calls)}",
                                "visual_anchor_region": {"x1": 0.0, "y1": 0.08, "x2": 1.0, "y2": 0.65},
                            },
                            "evidence": {
                                "staged_text_verified": True,
                                "staged_exact_text_verified": True,
                                "staged_exact_text_ocr_verified": True,
                                "input_cleared_after_send": True,
                                "post_action_screen_captured": True,
                                "outbound_message_verified": True,
                                "outbound_exact_text_verified": True,
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
                self.assertEqual(calls, messages)
                self.assertEqual(
                    second_action_request["target_binding"]["thread_evidence"]["visual_anchor_hash"],
                    f"fresh-{app_id}-1",
                )
                self.assertEqual(
                    second_action_request["target_binding"]["thread_evidence"]["observation_id"],
                    f"gui_post_send_{app_id}_1",
                )
                self.assertEqual(recorded_result["post_action_observation_id"], f"gui_post_send_{app_id}_2")

    def test_managed_iphone_mirroring_sequence_accepts_already_sent_prefix(self):
        for app_id, auth_id, match_id, candidate_key in (
            ("tinder", "auth_tinder_live", "match_tinder", "tinder_ada"),
            ("bumble", "auth_bumble_live", "match_bumble", "bumble_ada"),
        ):
            with self.subTest(app_id=app_id), tempfile.TemporaryDirectory() as temp_dir:
                root = Path(temp_dir)
                data_dir = root / "data"
                work_dir = root / "work"
                auth_path = root / f"{app_id}_auth.json"
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
                work_item.update({
                    "work_item_id": f"work_{app_id}_already_sent_sequence",
                    "action_request_id": f"act_{app_id}_already_sent_sequence",
                    "match_id": match_id,
                    "candidate_key": candidate_key,
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
                        authorization_id=auth_id,
                        target_match_id=match_id,
                        payload_hash=payload_hash,
                    ),
                    "target_binding": _iphone_current_thread_target_binding(app_id, match_id, candidate_key),
                })
                calls: list[str] = []
                second_action_request: dict[str, object] = {}
                recorded_result: dict[str, object] = {}

                def fake_run_cli_json(*args: str, allow_error: bool = False, **kwargs: object) -> dict[str, object]:
                    if len(args) >= 3 and args[0] == "harness" and args[1] == app_id and "send-message" in args:
                        text_path = Path(args[args.index("--text-file") + 1])
                        action_path = Path(args[args.index("--action-request") + 1])
                        calls.append(text_path.read_text(encoding="utf-8"))
                        if len(calls) == 1:
                            return {
                                "schema_version": 2,
                                "status": "ok",
                                "already_sent": True,
                                "post_action_observation_id": f"gui_post_send_{app_id}_existing_1",
                                "current_thread_visual_anchor": {
                                    "status": "ok",
                                    "screen_state": f"{app_id}_conversation",
                                    "visual_anchor_hash": f"fresh-{app_id}-existing",
                                    "visual_anchor_region": {"x1": 0.0, "y1": 0.08, "x2": 1.0, "y2": 0.65},
                                },
                                "evidence": {
                                    "staged_text_verified": False,
                                    "staged_exact_text_verified": False,
                                    "staged_exact_text_ocr_verified": False,
                                    "input_cleared_after_send": True,
                                    "post_action_screen_captured": True,
                                    "outbound_message_verified": True,
                                    "outbound_exact_text_verified": True,
                                    "outbound_exact_text_ocr_verified": True,
                                },
                            }
                        second_action_request.update(json.loads(action_path.read_text(encoding="utf-8")))
                        return {
                            "schema_version": 2,
                            "status": "ok",
                            "post_action_observation_id": f"gui_post_send_{app_id}_2",
                            "evidence": {
                                "staged_text_verified": True,
                                "staged_exact_text_verified": True,
                                "staged_exact_text_ocr_verified": True,
                                "input_cleared_after_send": True,
                                "post_action_screen_captured": True,
                                "outbound_message_verified": True,
                                "outbound_exact_text_verified": True,
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
                self.assertEqual(calls, messages)
                self.assertTrue(recorded_result["message_results"][0]["already_sent"])
                self.assertFalse(recorded_result["message_results"][0]["evidence"]["staged_text_verified"])
                self.assertEqual(
                    second_action_request["target_binding"]["thread_evidence"]["visual_anchor_hash"],
                    f"fresh-{app_id}-existing",
                )
                self.assertEqual(
                    second_action_request["target_binding"]["thread_evidence"]["observation_id"],
                    f"gui_post_send_{app_id}_existing_1",
                )
                self.assertEqual(recorded_result["post_action_observation_id"], f"gui_post_send_{app_id}_2")
