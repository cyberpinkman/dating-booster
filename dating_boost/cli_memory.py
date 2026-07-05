from __future__ import annotations

from dating_boost.cli_ops import *
from dating_boost.core.repositories import user_profile_from_dict as _core_user_profile_from_dict

def _handle_import_observation(args: argparse.Namespace) -> int:
    try:
        observation = load_observation(args.input)
    except (OSError, json.JSONDecodeError, KeyError, TypeError, ValueError) as exc:
        _print_json({
            "schema_version": 1,
            "status": "error",
            "reason": "invalid_observation",
            "message": str(exc),
        })
        return 2
    return _persist_observation(args.data_dir, observation)


def _handle_observe_screenshot(args: argparse.Namespace) -> int:
    if not args.screenshot.exists():
        raise ValueError(f"screenshot does not exist: {args.screenshot}")
    observation = build_observation_from_screenshot_analysis(
        screenshot_path=args.screenshot,
        analysis=_read_json_object(args.analysis),
    )
    return _persist_observation(args.data_dir, observation)


def _handle_observation_template(args: argparse.Namespace) -> int:
    _print_json(observation_template(args.type, args.app_id))
    return 0


def _handle_observation_validate(args: argparse.Namespace) -> int:
    payload = validate_observation(_read_json_object(args.input))
    _print_json(payload)
    return 0 if payload["status"] == "ok" else 2


def _handle_observation_normalize(args: argparse.Namespace) -> int:
    observation = normalize_observation(_read_json_object(args.input))
    validation = validate_observation(observation)
    payload = {
        "schema_version": 1,
        "status": validation["status"],
        "observation": observation,
        "validation": validation,
    }
    _print_json(payload)
    return 0 if validation["status"] == "ok" else 2


def _persist_observation(data_dir: Path, observation: AppObservation) -> int:
    _print_json(_store_observation(data_dir, observation))
    return 0


def _store_observation(data_dir: Path, observation: AppObservation) -> dict[str, Any]:
    payload = store_observation_with_memory(data_dir, observation)
    _validate_storage_id(str(payload["match_id"]), "match_id")
    _validate_storage_id(observation.observation_id, "observation_id")
    return payload


def _handle_memory_get_match(args: argparse.Namespace) -> int:
    for record in MatchRepository(args.data_dir).list_match_candidates():
        if record.get("match_id") == args.match_id:
            _print_json(
                {
                    "schema_version": 1,
                    "status": "ok",
                    "match": record,
                }
            )
            return 0
    _print_json(
        {
            "schema_version": 1,
            "status": "not_found",
            "match_id": args.match_id,
        }
    )
    return 2


def _handle_memory_rebuild(args: argparse.Namespace) -> int:
    if args.all:
        return _handle_memory_rebuild_all(args)
    try:
        payload = _rebuild_memory_match(args.data_dir, args.match_id)
        if payload is None:
            _print_json(
                {
                    "schema_version": 1,
                    "status": "not_found",
                    "match_id": args.match_id,
                }
            )
            return 2
    except (StorageError, ValueError, KeyError, TypeError) as exc:
        _print_json(
            {
                "schema_version": 1,
                "status": "error",
                "match_id": args.match_id,
                "reason": str(exc),
            }
        )
        return 2
    _print_json(payload)
    return 0


def _handle_memory_rebuild_all(args: argparse.Namespace) -> int:
    memory_repo = MemoryRepository(args.data_dir)
    match_ids = memory_repo.match_ids_with_observations()
    if not match_ids:
        _print_json(
            {
                "schema_version": 1,
                "status": "not_found",
                "rebuilt_count": 0,
                "error_count": 0,
                "matches": [],
            }
        )
        return 2

    results: list[dict[str, Any]] = []
    for match_id in match_ids:
        try:
            result = _rebuild_memory_match(args.data_dir, match_id)
        except (StorageError, ValueError, KeyError, TypeError) as exc:
            result = {
                "schema_version": 1,
                "status": "error",
                "match_id": match_id,
                "reason": str(exc),
            }
        if result is None:
            result = {
                "schema_version": 1,
                "status": "not_found",
                "match_id": match_id,
                "reason": "missing_observations",
            }
        results.append(result)

    rebuilt_count = sum(1 for item in results if item["status"] == "ok")
    error_count = len(results) - rebuilt_count
    status = "ok" if error_count == 0 else "partial"
    _print_json(
        {
            "schema_version": 1,
            "status": status,
            "rebuilt_count": rebuilt_count,
            "error_count": error_count,
            "matches": results,
        }
    )
    return 0 if status == "ok" else 2


def _rebuild_memory_match(data_dir: Path, match_id: str) -> dict[str, Any] | None:
    observations = ObservationRepository(data_dir).load_observations(match_id)
    if not observations:
        return None
    memory_repo = MemoryRepository(data_dir)
    match_record = _match_record(data_dir, match_id)
    projection = memory_repo.rebuild_projection_from_observations(
        match_id,
        observations,
        identity_confidence=(
            str(match_record["identity_confidence"])
            if match_record is not None and match_record.get("identity_confidence")
            else None
        ),
        requires_user_confirmation=(
            bool(match_record["requires_user_confirmation"])
            if match_record is not None and "requires_user_confirmation" in match_record
            else None
        ),
    )
    return {
        "schema_version": 1,
        "status": "ok",
        "match_id": match_id,
        "memory_event_count": len(memory_repo.load_events(match_id)),
        "projection_updated": True,
        "identity_status": projection.identity_status.value,
        "trusted_for_context": projection.trusted_for_context,
        "trusted_for_managed_send": projection.trusted_for_managed_send,
    }


def _handle_memory_update_match(args: argparse.Namespace) -> int:
    update = _read_json_object(args.input)
    try:
        payload = _apply_memory_update(args.data_dir, args.match_id, update)
    except (StorageError, ValueError) as exc:
        _print_json(
            {
                "schema_version": 1,
                "status": "error",
                "match_id": args.match_id,
                "reason": str(exc),
            }
        )
        return 2
    _print_json(payload)
    return 0


def _handle_memory_export(args: argparse.Namespace) -> int:
    try:
        export_payload = MemoryRepository(args.data_dir).export_match(args.match_id)
    except (StorageError, ValueError) as exc:
        _print_json(
            {
                "schema_version": 1,
                "status": "error",
                "match_id": args.match_id,
                "reason": str(exc),
            }
        )
        return 2
    status = "ok" if export_payload["projection"] is not None or export_payload["events"] else "not_found"
    _print_json(
        {
            "schema_version": 1,
            "status": status,
            "match_id": args.match_id,
            "export": export_payload,
        }
    )
    return 0 if status == "ok" else 2


def _handle_memory_delete_match(args: argparse.Namespace) -> int:
    required = f"delete-match:{args.match_id}"
    if args.confirm != required:
        _print_json(
            {
                "schema_version": 1,
                "status": "blocked",
                "match_id": args.match_id,
                "reason": "confirm_token_mismatch",
                "required_confirm_token": required,
            }
        )
        return 2

    try:
        prefix = f"matches/{args.match_id}/"
        deleted_sqlite_documents = 0
        deleted_sqlite_events = 0
        store = ProductionDataStore(args.data_dir)
        if (args.data_dir / "dating_boost.sqlite3").exists():
            deleted_sqlite_documents = store.delete_documents_with_prefix(prefix)
            deleted_sqlite_events = store.delete_audit_events_with_stream_prefix(prefix)
        match_repo = MatchRepository(args.data_dir)
        removed_identity_confirmations = match_repo.remove_identity_confirmations(args.match_id)
        removed_index_records = match_repo.delete_match(args.match_id)
        deleted_json_files = MemoryRepository(args.data_dir).delete_match_documents(args.match_id)
    except (OSError, RuntimeError, StorageError, ValueError) as exc:
        _print_json(
            {
                "schema_version": 1,
                "status": "error",
                "match_id": args.match_id,
                "reason": str(exc),
            }
        )
        return 2

    _print_json(
        {
            "schema_version": 1,
            "status": "ok",
            "match_id": args.match_id,
            "deleted_json_files": deleted_json_files,
            "deleted_sqlite_documents": deleted_sqlite_documents,
            "deleted_sqlite_events": deleted_sqlite_events,
            "removed_identity_confirmations": removed_identity_confirmations,
            "removed_index_records": removed_index_records,
        }
    )
    return 0


def _handle_memory_propose(args: argparse.Namespace) -> int:
    from dating_boost.core.memory.proposals import extract_proposals
    from dating_boost.core.memory.review_queue import ReviewQueueRepository
    from dating_boost.perception.fixture_loader import load_observation

    observation = load_observation(args.input)
    memory_repo = MemoryRepository(args.data_dir)
    projection = memory_repo.load_projection(args.match_id)
    if projection is None:
        _print_json({"schema_version": 1, "status": "not_found", "match_id": args.match_id})
        return 2
    proposals = extract_proposals(
        args.match_id,
        observation,
        projection,
        session_id=args.session_id or None,
        observation_id=observation.observation_id,
        source="deterministic",
    )
    if args.store_review_queue:
        review_repo = ReviewQueueRepository(args.data_dir)
        enqueued = []
        for proposal in proposals:
            if review_repo.reject_dedupe_key_exists(proposal.dedupe_key):
                continue
            review_repo.enqueue(proposal)
            enqueued.append(proposal.to_dict())
        _print_json({
            "schema_version": 1,
            "status": "ok",
            "match_id": args.match_id,
            "enqueued_count": len(enqueued),
            "items": enqueued,
        })
    else:
        _print_json({
            "schema_version": 1,
            "status": "ok",
            "match_id": args.match_id,
            "proposal_count": len(proposals),
            "items": [item.to_dict() for item in proposals],
        })
    return 0


def _handle_memory_review_list(args: argparse.Namespace) -> int:
    from dating_boost.core.memory.review_queue import ReviewQueueRepository

    review_repo = ReviewQueueRepository(args.data_dir)
    items = review_repo.load_items(
        status=args.status or None,
        match_id=args.match_id,
        session_id=args.session_id,
    )
    _print_json({
        "schema_version": 1,
        "status": "ok",
        "count": len(items),
        "items": [item.to_dict() for item in items],
    })
    return 0


def _handle_memory_review_decide(args: argparse.Namespace) -> int:
    from dating_boost.core.memory.review_queue import ReviewQueueRepository

    accept_ids = list(args.accept or [])
    reject_ids = list(args.reject or [])
    if not accept_ids and not reject_ids:
        _print_json({"schema_version": 1, "status": "error", "reason": "no_ids_provided"})
        return 2
    confirm_token = str(args.confirm or "")
    if not confirm_token.startswith("memory-review:"):
        _print_json({
            "schema_version": 1,
            "status": "blocked",
            "reason": "confirm_token_mismatch",
            "required_format": "memory-review:<session_id>",
        })
        return 2
    confirm_session_id = confirm_token[len("memory-review:"):]
    review_repo = ReviewQueueRepository(args.data_dir)
    all_ids = [*accept_ids, *reject_ids]
    target_items = review_repo.load_items()
    id_to_item = {item.review_item_id: item for item in target_items}
    for item_id in all_ids:
        item = id_to_item.get(item_id)
        if item is None:
            _print_json({
                "schema_version": 1,
                "status": "error",
                "reason": f"review_item_not_found:{item_id}",
            })
            return 2
        if item.session_id != confirm_session_id:
            _print_json({
                "schema_version": 1,
                "status": "blocked",
                "reason": "confirm_token_session_mismatch",
                "item_id": item_id,
                "item_session_id": item.session_id,
                "confirm_session_id": confirm_session_id,
            })
            return 2
        if item.status != "pending":
            _print_json({
                "schema_version": 1,
                "status": "error",
                "reason": f"item_not_pending:{item_id}",
                "current_status": item.status,
            })
            return 2
    memory_repo = MemoryRepository(args.data_dir)
    accepted = []
    rejected = []
    errors = []
    for item_id in accept_ids:
        try:
            item = id_to_item[item_id]
            proposal = item.proposal
            scope = MemoryScope(proposal.get("scope", MemoryScope.MATCH_PROFILE.value))
            fact_type = MemoryFactType(proposal.get("fact_type", MemoryFactType.VISIBLE_FACT.value))
            predicate = str(proposal.get("predicate", ""))
            value = proposal.get("value")
            projection = memory_repo.load_projection(item.match_id)
            if projection is not None and not projection.trusted_for_context:
                identity_predicates = {"identity", "real_name", "phone_number", "email", "address"}
                if predicate not in identity_predicates:
                    errors.append({
                        "id": item_id,
                        "action": "accept",
                        "reason": "identity_not_trusted",
                    })
                    continue
            fact = MemoryFact(
                fact_id=item.review_item_id,
                scope=scope,
                fact_type=fact_type,
                subject=proposal.get("subject", ""),
                predicate=predicate,
                value=value,
                qualifiers=dict(proposal.get("qualifiers", {})),
                confidence=proposal.get("confidence", "medium"),
                evidence=EvidenceRef(
                    source_type="memory_review",
                    evidence_text=str(proposal.get("evidence_text", "")),
                    confidence=proposal.get("confidence", "medium"),
                    source_observation_id=item.observation_id,
                    metadata={
                        "dedupe_key": item.dedupe_key,
                        "review_source": item.source,
                        "risk": item.risk,
                        "session_id": item.session_id,
                    },
                ),
                created_at=item.created_at,
                last_seen_at=item.created_at,
            )
            event = MemoryEvent(
                event_id=_memory_event_id(item.match_id, "review_accept", {"review_item_id": item_id}),
                event_type=MemoryEventType.PROFILE_FACT_OBSERVED,
                match_id=item.match_id,
                scope=scope,
                created_at=_now_iso(),
                payload={
                    "fact": fact.to_dict(),
                    "review_item_id": item_id,
                    "source": "memory_review",
                    "review_source": item.source,
                    "risk": item.risk,
                    "dedupe_key": item.dedupe_key,
                    "observation_id": item.observation_id,
                    "session_id": item.session_id,
                },
                evidence=fact.evidence,
            )
            memory_repo.append_event(item.match_id, event)
            memory_repo.rebuild_projection(item.match_id)
            review_repo.update_status(item_id, "accepted")
            accepted.append(item_id)
        except (ValueError, StorageError) as exc:
            errors.append({"id": item_id, "action": "accept", "reason": str(exc)})
    for item_id in reject_ids:
        try:
            review_repo.update_status(item_id, "rejected")
            rejected.append(item_id)
        except ValueError as exc:
            errors.append({"id": item_id, "action": "reject", "reason": str(exc)})
    _print_json({
        "schema_version": 1,
        "status": "ok" if not errors else "partial",
        "accepted": accepted,
        "rejected": rejected,
        "errors": errors,
    })
    return 0 if not errors else 2


def _apply_memory_update(data_dir: Path, match_id: str, update: dict[str, Any]) -> dict[str, Any]:
    action = str(update.get("action") or "")
    if action == "merge_identity":
        return _apply_memory_identity_merge(data_dir, match_id, update)
    if action == "inherit_memory":
        return _apply_memory_inheritance(data_dir, match_id, update)

    memory_repo = MemoryRepository(data_dir)
    event = _memory_update_event(data_dir, match_id, update)
    memory_repo.append_event(match_id, event)
    projection = memory_repo.rebuild_projection(match_id)
    return {
        "schema_version": 1,
        "status": "ok",
        "match_id": match_id,
        "action": action,
        "event_id": event.event_id,
        "projection_updated": True,
        "identity_status": projection.identity_status.value,
        "trusted_for_context": projection.trusted_for_context,
        "trusted_for_managed_send": projection.trusted_for_managed_send,
    }


def _apply_memory_identity_merge(data_dir: Path, match_id: str, update: dict[str, Any]) -> dict[str, Any]:
    source_match_id = str(update.get("source_match_id") or "")
    target_match_id = str(update.get("target_match_id") or "")
    confirmation_token = str(update.get("confirmation_token") or "")
    expected_token = f"merge_identity:{source_match_id}:{target_match_id}"
    if not source_match_id or not target_match_id:
        raise ValueError("merge_identity requires source_match_id and target_match_id")
    if target_match_id != match_id:
        raise ValueError("merge_identity target_match_id must match --match-id")
    if confirmation_token != expected_token:
        raise ValueError(f"merge_identity requires confirmation_token {expected_token!r}")

    memory_repo = MemoryRepository(data_dir)
    observation_repo = ObservationRepository(data_dir)
    source_events = memory_repo.load_events(source_match_id)
    target_events_before = memory_repo.load_events(target_match_id)
    for observation in observation_repo.load_observations(source_match_id):
        observation_repo.save_observation(target_match_id, observation)
    MatchRepository(data_dir).merge_matches(
        source_match_id=source_match_id,
        target_match_id=target_match_id,
    )
    for source_event in source_events:
        memory_repo.append_event(
            target_match_id,
            _merged_memory_event(
                source_event,
                source_match_id=source_match_id,
                target_match_id=target_match_id,
            ),
        )
    event = MemoryEvent(
        event_id=_memory_event_id(
            target_match_id,
            "merge_identity",
            {"source_match_id": source_match_id, "target_match_id": target_match_id},
        ),
        event_type=MemoryEventType.MATCH_IDENTITY_CONFIRMED,
        match_id=target_match_id,
        scope=MemoryScope.MATCH_PROFILE,
        created_at=_now_iso(),
        payload={
            "confirmed_by": str(update.get("confirmed_by") or "user"),
            "action": "merge_identity",
            "source_match_id": source_match_id,
            "target_match_id": target_match_id,
            "merged_event_count": len(source_events),
            "target_event_count_before_merge": len(target_events_before),
        },
        evidence=_manual_evidence("identity_merge", "User confirmed identity merge."),
    )
    memory_repo.append_event(target_match_id, event)
    projection = memory_repo.rebuild_projection(target_match_id)
    return {
        "schema_version": 1,
        "status": "ok",
        "match_id": target_match_id,
        "action": "merge_identity",
        "event_id": event.event_id,
        "source_match_id": source_match_id,
        "target_match_id": target_match_id,
        "merged_event_count": len(source_events),
        "projection_updated": True,
        "identity_status": projection.identity_status.value,
        "trusted_for_context": projection.trusted_for_context,
        "trusted_for_managed_send": projection.trusted_for_managed_send,
    }


def _memory_update_event(data_dir: Path, match_id: str, update: dict[str, Any]) -> MemoryEvent:
    action = str(update.get("action") or "")
    created_at = str(update.get("created_at") or _now_iso())
    if action == "confirm_identity":
        return MemoryEvent(
            event_id=_memory_event_id(match_id, action, update),
            event_type=MemoryEventType.MATCH_IDENTITY_CONFIRMED,
            match_id=match_id,
            scope=MemoryScope.MATCH_PROFILE,
            created_at=created_at,
            payload={
                "confirmed_by": str(update.get("confirmed_by") or "user"),
                "action": action,
            },
            evidence=_manual_evidence("user_confirmation", "User confirmed match identity."),
        )
    if action in {"reject_fact", "archive_fact"}:
        target_fact_id = _required_text(update, "target_fact_id")
        return MemoryEvent(
            event_id=_memory_event_id(match_id, action, update),
            event_type=MemoryEventType.FACT_REJECTED if action == "reject_fact" else MemoryEventType.FACT_ARCHIVED,
            match_id=match_id,
            scope=MemoryScope.MATCH_PROFILE,
            created_at=created_at,
            payload={
                "target_fact_id": target_fact_id,
                "reason": str(update.get("reason") or action),
            },
            evidence=_manual_evidence("user_correction", f"User requested {action}."),
        )
    if action == "correct_fact":
        target_fact_id = _required_text(update, "target_fact_id")
        fact = _corrected_fact(data_dir, match_id, target_fact_id, update, created_at)
        return MemoryEvent(
            event_id=_memory_event_id(match_id, action, update),
            event_type=MemoryEventType.FACT_CORRECTED,
            match_id=match_id,
            scope=MemoryScope.MATCH_PROFILE,
            created_at=created_at,
            payload={
                "target_fact_id": target_fact_id,
                "fact": fact.to_dict(),
                "reason": str(update.get("reason") or "user_correction"),
            },
            evidence=_manual_evidence("user_correction", "User corrected a memory fact."),
        )
    if action == "create_commitment":
        commitment = CommitmentMemory(
            commitment_id=str(update.get("commitment_id") or f"commitment_{_digest(update)[:12]}"),
            text=_required_text(update, "text"),
            evidence=_manual_evidence("user_update", "User created a commitment memory."),
            created_at=created_at,
            last_seen_at=created_at,
        )
        return MemoryEvent(
            event_id=_memory_event_id(match_id, action, update),
            event_type=MemoryEventType.COMMITMENT_CREATED,
            match_id=match_id,
            scope=MemoryScope.COMMITMENT,
            created_at=created_at,
            payload={"commitment": commitment.to_dict()},
            evidence=commitment.evidence,
        )
    if action == "resolve_commitment":
        commitment_id = _required_text(update, "commitment_id")
        return MemoryEvent(
            event_id=_memory_event_id(match_id, action, update),
            event_type=MemoryEventType.COMMITMENT_RESOLVED,
            match_id=match_id,
            scope=MemoryScope.COMMITMENT,
            created_at=created_at,
            payload={
                "commitment_id": commitment_id,
                "resolved_at": str(update.get("resolved_at") or created_at),
            },
            evidence=_manual_evidence("user_update", "User resolved a commitment memory."),
        )
    raise ValueError(f"unsupported memory update action: {action!r}")


def _corrected_fact(
    data_dir: Path,
    match_id: str,
    target_fact_id: str,
    update: dict[str, Any],
    created_at: str,
) -> MemoryFact:
    if isinstance(update.get("fact"), dict):
        fact_data = dict(update["fact"])
        fact_data.setdefault("evidence", _manual_evidence("user_correction", "User corrected a memory fact.").to_dict())
        fact_data.setdefault("created_at", created_at)
        fact_data.setdefault("last_seen_at", created_at)
        fact_data.setdefault("fact_type", MemoryFactType.USER_CONFIRMED.value)
        return MemoryFact.from_dict(fact_data)
    target = _find_memory_fact(data_dir, match_id, target_fact_id)
    subject = str(update.get("subject") or (target.subject if target else match_id))
    predicate = str(update.get("predicate") or (target.predicate if target else "user_corrected_fact"))
    qualifiers = dict(update.get("qualifiers") or (target.qualifiers if target else {}))
    return MemoryFact(
        fact_id=str(update.get("fact_id") or "manual_corrected_fact"),
        scope=MemoryScope.MATCH_PROFILE,
        fact_type=MemoryFactType.USER_CONFIRMED,
        subject=subject,
        predicate=predicate,
        value=update.get("value"),
        qualifiers=qualifiers,
        confidence=str(update.get("confidence") or "high"),
        evidence=_manual_evidence("user_correction", "User corrected a memory fact."),
        created_at=created_at,
        last_seen_at=created_at,
    )


def _find_memory_fact(data_dir: Path, match_id: str, fact_id: str) -> MemoryFact | None:
    projection = MemoryRepository(data_dir).load_projection(match_id)
    if projection is None:
        return None
    for fact in [*projection.facts, *projection.inferences]:
        if fact.fact_id == fact_id:
            return fact
    return None


def _merged_memory_event(
    event: MemoryEvent,
    *,
    source_match_id: str,
    target_match_id: str,
) -> MemoryEvent:
    payload = dict(event.payload)
    payload["original_match_id"] = source_match_id
    payload["original_event_id"] = event.event_id
    return MemoryEvent(
        event_id=f"merged_{_digest({'source': source_match_id, 'target': target_match_id, 'event_id': event.event_id})[:16]}",
        event_type=event.event_type,
        match_id=target_match_id,
        scope=event.scope,
        created_at=event.created_at,
        payload=payload,
        evidence=EvidenceRef(
            source_type="identity_merge",
            source_event_id=event.event_id,
            evidence_text="Source match memory event preserved during identity merge.",
            metadata={"source_match_id": source_match_id},
        ),
    )


def _apply_memory_inheritance(data_dir: Path, match_id: str, update: dict[str, Any]) -> dict[str, Any]:
    source_match_id = str(update.get("source_match_id") or "")
    target_match_id = str(update.get("target_match_id") or "")
    confirmation_token = str(update.get("confirmation_token") or "")
    direction = str(update.get("direction") or "dating_app_to_wechat")
    expected_token = f"inherit_memory:{source_match_id}:{target_match_id}"
    if not source_match_id or not target_match_id:
        raise ValueError("inherit_memory requires source_match_id and target_match_id")
    if source_match_id == target_match_id:
        raise ValueError("inherit_memory source_match_id and target_match_id must differ")
    if target_match_id != match_id:
        raise ValueError("inherit_memory target_match_id must match --match-id")
    if confirmation_token != expected_token:
        raise ValueError(f"inherit_memory requires confirmation_token {expected_token!r}")

    memory_repo = MemoryRepository(data_dir)
    source_events = memory_repo.load_events(source_match_id)
    if not source_events:
        raise ValueError(f"source match {source_match_id!r} has no memory events")
    if memory_repo.load_projection(target_match_id) is None and not memory_repo.load_events(target_match_id):
        raise ValueError(f"target match {target_match_id!r} does not exist")

    target_events_before = memory_repo.load_events(target_match_id)
    existing_inherited_ids = {
        event.payload.get("original_event_id")
        for event in target_events_before
        if event.evidence is not None
        and event.evidence.source_type == "memory_inheritance"
        and event.payload.get("original_event_id")
    }
    _inheritable_types = {
        MemoryEventType.PROFILE_FACT_OBSERVED,
        MemoryEventType.CONVERSATION_FACT_OBSERVED,
        MemoryEventType.INFERENCE_RECORDED,
        MemoryEventType.FACT_CORRECTED,
        MemoryEventType.FACT_REJECTED,
        MemoryEventType.FACT_ARCHIVED,
        MemoryEventType.COMMITMENT_CREATED,
        MemoryEventType.COMMITMENT_RESOLVED,
        MemoryEventType.FEEDBACK_RECORDED,
    }
    now = _now_iso()
    inherited_count = 0
    skipped_count = 0
    skipped_type_count = 0
    for source_event in source_events:
        if source_event.event_type not in _inheritable_types:
            skipped_type_count += 1
            continue
        if source_event.event_id in existing_inherited_ids:
            skipped_count += 1
            continue
        inherited_event = _inherited_memory_event(
            source_event,
            source_match_id=source_match_id,
            target_match_id=target_match_id,
            direction=direction,
            inherited_at=now,
        )
        memory_repo.append_event(target_match_id, inherited_event)
        inherited_count += 1

    summary_event = MemoryEvent(
        event_id=_memory_event_id(
            target_match_id,
            "inherit_memory",
            {"source_match_id": source_match_id, "target_match_id": target_match_id, "direction": direction},
        ),
        event_type=MemoryEventType.PROJECTION_REBUILT,
        match_id=target_match_id,
        scope=MemoryScope.MATCH_PROFILE,
        created_at=now,
        payload={
            "action": "inherit_memory",
            "source_match_id": source_match_id,
            "target_match_id": target_match_id,
            "direction": direction,
            "confirmed_by": str(update.get("confirmed_by") or "user"),
            "inherited_event_count": inherited_count,
            "skipped_existing_event_count": skipped_count,
            "skipped_non_inheritable_event_count": skipped_type_count,
        },
        evidence=_manual_evidence("memory_inheritance_summary", f"User authorized one-way memory inheritance from {source_match_id} to {target_match_id}."),
    )
    memory_repo.append_event(target_match_id, summary_event)
    projection = memory_repo.rebuild_projection(target_match_id)
    return {
        "schema_version": 1,
        "status": "ok",
        "match_id": target_match_id,
        "action": "inherit_memory",
        "event_id": summary_event.event_id,
        "source_match_id": source_match_id,
        "target_match_id": target_match_id,
        "inherited_event_count": inherited_count,
        "skipped_existing_event_count": skipped_count,
        "skipped_non_inheritable_event_count": skipped_type_count,
        "projection_updated": True,
        "identity_status": projection.identity_status.value,
        "trusted_for_context": projection.trusted_for_context,
        "trusted_for_managed_send": projection.trusted_for_managed_send,
    }


def _inherited_memory_event(
    event: MemoryEvent,
    *,
    source_match_id: str,
    target_match_id: str,
    direction: str,
    inherited_at: str,
) -> MemoryEvent:
    payload = dict(event.payload)
    payload["inheritance_type"] = direction
    payload["source_match_id"] = source_match_id
    payload["original_event_id"] = event.event_id
    payload["inherited_at"] = inherited_at
    return MemoryEvent(
        event_id=f"inherited_{_digest({'source': source_match_id, 'target': target_match_id, 'event_id': event.event_id, 'action': 'inherit_memory'})[:16]}",
        event_type=event.event_type,
        match_id=target_match_id,
        scope=event.scope,
        created_at=event.created_at,
        payload=payload,
        evidence=EvidenceRef(
            source_type="memory_inheritance",
            source_event_id=event.event_id,
            evidence_text="Memory event inherited from source match via user-authorized one-way transfer.",
            metadata={"source_match_id": source_match_id, "inheritance_type": direction},
        ),
    )


def _memory_event_id(match_id: str, action: str, payload: dict[str, Any]) -> str:
    return f"mem_evt_{_digest({'match_id': match_id, 'action': action, 'payload': payload})[:16]}"


def _manual_evidence(source_type: str, evidence_text: str) -> EvidenceRef:
    return EvidenceRef(source_type=source_type, evidence_text=evidence_text, confidence="user_confirmed")


def _required_text(payload: dict[str, Any], key: str) -> str:
    value = str(payload.get(key) or "")
    if not value:
        raise ValueError(f"{key} is required")
    return value


def _match_record(data_dir: Path, match_id: str) -> dict[str, object] | None:
    for record in MatchRepository(data_dir).list_match_candidates():
        if record.get("match_id") == match_id:
            return record
    return None


def _handle_draft(args: argparse.Namespace) -> int:
    reply_mode = ReplyMode(args.mode)
    backend = _select_backend(args)
    observation = ObservationRepository(args.data_dir).load_latest_observation(args.match_id)
    evidence = build_draft_evidence(
        args.data_dir,
        args.match_id,
        reply_mode=reply_mode,
        observation=observation,
        draft_kind=args.draft_kind,
        user_reactivated=bool(args.reactivation_requested),
        now=_now_iso(),
        app_id=observation.app_id if observation else None,
        runtime=_observation_runtime(observation),
        require_user_profile_source=True,
    )
    if evidence.status != "ok":
        _print_json(
            {
                "schema_version": 1,
                "status": "blocked",
                "match_id": args.match_id,
                "mode": reply_mode.value,
                "evidence_status": evidence.status,
                "draft_evidence": evidence.public_dict(),
            }
        )
        return 2

    generation = generate_reply_with_refinement(
        evidence,
        backend=backend,
        audit_root=args.data_dir,
    )
    _record_support_draft_generation(args.data_dir, evidence=evidence, generation=generation, command="draft")
    if generation.status != "ok" or generation.draft is None or generation.draft_payload is None:
        _print_json(
            {
                "schema_version": 1,
                "status": "blocked",
                "match_id": args.match_id,
                "mode": reply_mode.value,
                "evidence_status": evidence.status,
                "draft_evidence": evidence.public_dict(),
                "draft_generation_summary": generation.summary(),
                "self_review_attempts": generation.summary()["self_review_attempts"],
            }
        )
        return 2

    draft = generation.draft
    context_pack = evidence.context_pack
    disclosure_profile = UserDisclosureRepository(args.data_dir).load_profile_or_none()
    review = review_draft(
        generation.draft_payload,
        context_pack,
        mode="display",
        observation=observation,
        planner_recommendation=evidence.planner_recommendation,
        disclosure_profile=disclosure_profile,
    )
    DraftReviewAuditRepository(args.data_dir).append_review(
        review,
        draft_payload=generation.draft_payload,
        context_pack=context_pack,
        mode="display",
        target_match_id=args.match_id,
    )
    _record_support_draft_review(
        args.data_dir,
        draft_payload=generation.draft_payload,
        context_pack=context_pack,
        review=review,
        command="draft",
    )

    if not review.allowed_for_display:
        _print_json(
            {
                "status": "blocked",
                "match_id": args.match_id,
                "mode": reply_mode.value,
                "evidence_status": evidence.status,
                "draft_generation_summary": generation.summary(),
                "self_review_attempts": generation.summary()["self_review_attempts"],
                "draft_review": _draft_review_public_dict(review),
            }
        )
        return 2

    payload: dict[str, Any] = {
        "status": review.status,
        "match_id": args.match_id,
        "mode": reply_mode.value,
        "evidence_status": evidence.status,
        "draft_evidence": evidence.public_dict(),
        "draft_generation_summary": generation.summary(),
        "self_review_attempts": generation.summary()["self_review_attempts"],
        "best_reply": draft.best_reply,
        "draft": generation.draft_payload,
        "draft_review": _draft_review_public_dict(review),
    }
    if args.debug_context:
        payload["context_pack"] = context_pack
        payload["draft_prompt"] = generation.prompt.public_dict()
    _print_json(payload)
    return 0


def _handle_context_build(args: argparse.Namespace) -> int:
    if args.max_memory_items is not None and args.max_memory_items < 1:
        _print_json(
            {
                "schema_version": 1,
                "status": "error",
                "reason": "max_memory_items_must_be_positive",
            }
        )
        return 2
    reply_mode = ReplyMode(args.mode)
    observation = ObservationRepository(args.data_dir).load_latest_observation(args.match_id)
    if args.include_draft_evidence:
        evidence = build_draft_evidence(
            args.data_dir,
            args.match_id,
            reply_mode=reply_mode,
            observation=observation,
            draft_kind=args.draft_kind,
            user_reactivated=bool(args.reactivation_requested),
            now=_now_iso(),
            app_id=observation.app_id if observation else None,
            runtime=_observation_runtime(observation),
            max_memory_items=args.max_memory_items,
            require_user_profile_source=True,
        )
        payload: dict[str, Any] = {
            "schema_version": 1,
            "status": evidence.status,
            "match_id": args.match_id,
            "mode": reply_mode.value,
            "draft_evidence": evidence.public_dict(),
        }
        if evidence.status == "ok":
            payload["context_pack"] = evidence.context_pack
        _print_json(payload)
        return 0 if evidence.status == "ok" else 2

    profile = JsonMemoryRepository(args.data_dir).load_user_profile()
    context_pack = _build_mvp_context_pack(
        profile,
        args.match_id,
        reply_mode,
        observation,
        args.data_dir,
        max_memory_items=args.max_memory_items,
        include_memory_diagnostics=bool(args.include_memory_diagnostics),
        semantic_provider=args.semantic_provider,
        semantic_query=args.semantic_query,
    )
    _print_json(
        {
            "schema_version": 1,
            "status": "ok",
            "match_id": args.match_id,
            "mode": reply_mode.value,
            "context_pack": context_pack,
        }
    )
    return 0


def _handle_policy_check_draft(args: argparse.Namespace) -> int:
    draft_payload = _read_json_object(args.input)
    context_payload = _read_json_object(args.context)
    context_pack = context_payload.get("context_pack", context_payload)
    if not isinstance(context_pack, dict):
        raise ValueError("--context must contain a JSON object or a context_pack object")
    mode = str(args.review_mode).replace("-", "_")
    review = review_draft(draft_payload, context_pack, mode=mode)
    if args.data_dir is not None:
        DraftReviewAuditRepository(args.data_dir).append_review(
            review,
            draft_payload=draft_payload,
            context_pack=context_pack,
            mode=mode,
        )
        _record_support_draft_review(
            args.data_dir,
            draft_payload=draft_payload,
            context_pack=context_pack,
            review=review,
        )
    allowed = {
        "display": review.allowed_for_display,
        "stage": review.allowed_for_stage,
        "managed_live": review.allowed_for_managed_send,
    }[mode]
    _print_json(
        {
            "schema_version": 1,
            "status": review.status,
            "draft_review": _draft_review_public_dict(review),
        }
    )
    return 0 if allowed else 2


def _handle_planner_update(args: argparse.Namespace) -> int:
    observation = load_observation(args.observation)
    assessment = _read_json_object(args.assessment)
    try:
        payload = PlannerRepository(args.data_dir).update_plan(
            match_id=args.match_id,
            goal_id=args.goal_id,
            observation=observation,
            assessment=assessment,
            now=_now_iso(),
            goal_type=args.goal_type,
        )
    except ValueError as exc:
        _print_json({"schema_version": 1, "status": "error", "reason": str(exc)})
        return 2
    _print_json(payload)
    return 0


def _handle_planner_get(args: argparse.Namespace) -> int:
    payload = PlannerRepository(args.data_dir).get_plan_payload(args.match_id)
    _print_json(payload)
    return 0 if payload["status"] == "ok" else 2


def _handle_planner_recommend(args: argparse.Namespace) -> int:
    payload = PlannerRepository(args.data_dir).recommend(args.match_id)
    _print_json(payload)
    return 0 if payload["status"] == "ok" else 2


def _handle_planner_event_log(args: argparse.Namespace) -> int:
    _print_json(PlannerRepository(args.data_dir).event_log_payload(args.match_id))
    return 0


def _handle_action_record_result(args: argparse.Namespace) -> int:
    payload = _read_json_object(args.input)
    try:
        event = ActionAuditRepository(args.data_dir).append_action_result(
            payload,
            created_at=MVP_TIMESTAMP,
        )
    except ValueError as exc:
        _print_json(
            {
                "schema_version": 1,
                "status": "error",
                "reason": str(exc),
            }
        )
        return 2

    AutomationRepository(args.data_dir).apply_action_result(event)

    _print_json(
        {
            "schema_version": 1,
            "status": "ok",
            "event_id": event["event_id"],
            "action_request_id": event.get("action_request_id"),
            "result_status": event["result_status"],
            "path": "audit/action_results.jsonl",
        }
    )
    return 0


def _handle_action_record_correction(args: argparse.Namespace) -> int:
    payload = _read_json_object(args.input)
    try:
        event = ActionAuditRepository(args.data_dir).append_correction(
            payload,
            created_at=_now_iso(),
        )
    except ValueError as exc:
        _print_json(
            {
                "schema_version": 1,
                "status": "error",
                "reason": str(exc),
            }
        )
        return 2

    _print_json(
        {
            "schema_version": 1,
            "status": "ok",
            "event_id": event["event_id"],
            "corrects_event_id": event.get("corrects_event_id"),
            "path": "audit/action_corrections.jsonl",
        }
    )
    return 0


def _build_mvp_context_pack(
    profile: UserProfile,
    match_id: str,
    reply_mode: ReplyMode,
    observation: AppObservation | None,
    data_dir: Path | None = None,
    *,
    max_memory_items: int | None = None,
    include_memory_diagnostics: bool = False,
    semantic_provider: str = "none",
    semantic_query: str | None = None,
) -> dict[str, Any]:
    now = _now_iso()
    user_profile = _profile_to_context_dict(profile)
    if data_dir is not None:
        disclosure_repo = UserDisclosureRepository(data_dir)
        disclosure_profile = disclosure_repo.load_profile_or_none()
        if disclosure_profile is not None:
            user_profile["disclosure_profile"] = disclosure_profile
        user_profile["disclosure_readiness"] = disclosure_repo.readiness(mode="draft")
    memory_context: dict[str, Any] | None = None
    if data_dir is not None:
        projection = MemoryRepository(data_dir).load_projection(match_id)
        if projection is not None:
            hook_provider = _semantic_hook_provider(semantic_provider)
            memory_context = build_memory_context(
                match_id,
                projection,
                latest_observation=observation,
                now=now,
                max_items=max_memory_items,
                reply_mode=reply_mode.value,
                semantic_hook_provider=hook_provider,
                semantic_query=semantic_query,
            )
    if memory_context is not None:
        match_profile = dict(memory_context["match_profile"])
        conversation_memory = dict(memory_context["conversation_memory"])
        conversation_memory["memory_items"] = memory_context.get("memory_items")
        if include_memory_diagnostics:
            conversation_memory["excluded_memory"] = memory_context.get("excluded_memory")
        if max_memory_items is not None:
            _suppress_unbudgeted_memory_context(match_profile, conversation_memory)
    elif observation is None:
        match_profile = {
            "match_id": match_id,
            "conversation_hooks": [],
            "possible_interests": [],
        }
        conversation_memory = {
            "recent_messages": [],
            "open_threads": [],
            "commitments": [],
            "running_summary": "No imported observation was available for this match.",
        }
    else:
        match_profile = _match_profile_from_observation(match_id, observation)
        conversation_memory = _conversation_memory_from_observation(observation)
    if data_dir is not None:
        conversation_memory.update(planner_context_items(PlannerRepository(data_dir).load_plan(match_id)))

    return build_context_pack(
        user_profile=user_profile,
        match_profile=match_profile,
        conversation_memory=conversation_memory,
        reply_mode=reply_mode,
        max_items=None,
        current_time_iso=now,
    )


def _suppress_unbudgeted_memory_context(
    match_profile: dict[str, Any],
    conversation_memory: dict[str, Any],
) -> None:
    match_profile["conversation_hooks"] = []
    match_profile["possible_interests"] = []
    conversation_memory["recent_messages"] = []
    conversation_memory["latest_inbound_messages"] = []
    conversation_memory["open_threads"] = []
    conversation_memory["commitments"] = []
    conversation_memory["running_summary"] = ""


def _semantic_hook_provider(name: str):
    from dating_boost.core.memory.semantic import (
        LocalLexicalSemanticHookProvider,
        NoOpSemanticHookProvider,
    )
    if name == "lexical":
        return LocalLexicalSemanticHookProvider()
    return NoOpSemanticHookProvider()


def _match_profile_from_observation(match_id: str, observation: AppObservation) -> dict[str, Any]:
    profile = observation.profile_observation
    possible_interest_cues = [*profile.photo_cues, *profile.hook_candidates]
    return {
        "match_id": match_id,
        "display_name": observation.match_identity_hints.visible_name,
        "profile_text": profile.profile_text,
        "conversation_hooks": list(profile.hook_candidates),
        "possible_interests": [
            {"name": cue, "confidence": "medium"}
            for cue in possible_interest_cues
        ],
    }


def _conversation_memory_from_observation(observation: AppObservation) -> dict[str, Any]:
    conversation = observation.conversation_observation
    visible_messages = [dict(message) for message in conversation.visible_messages]
    latest_inbound_messages = [dict(message) for message in conversation.latest_inbound_messages]
    return {
        "recent_messages": visible_messages,
        "latest_inbound_messages": latest_inbound_messages,
        "open_threads": list(conversation.thread_cues),
        "commitments": [],
        "running_summary": _observation_summary(observation),
    }


def _observation_runtime(observation: AppObservation | None) -> str | None:
    if observation is None:
        return None
    runtime = observation.provenance.get("runtime") or observation.provenance.get("harness_runtime")
    return str(runtime) if runtime else "default"


def _observation_summary(observation: AppObservation) -> str:
    profile_text = observation.profile_observation.profile_text.strip()
    messages = observation.conversation_observation.visible_messages
    latest_inbound = observation.conversation_observation.latest_inbound_messages
    latest_message = (
        latest_inbound[-1].get("text", "").strip()
        if latest_inbound
        else messages[-1].get("text", "").strip()
        if messages
        else ""
    )
    parts = [part for part in [profile_text, latest_message] if part]
    if parts:
        return " ".join(parts)
    return "Imported observation contained no visible conversation text."


def _profile_from_dict(data: dict[str, Any]) -> UserProfile:
    return _core_user_profile_from_dict(data)


def _profile_to_context_dict(profile: UserProfile) -> dict[str, Any]:
    return {
        "facts": [item.to_dict() for item in profile.facts],
        "preferences": [item.to_dict() for item in profile.preferences],
        "boundaries": [item.to_dict() for item in profile.boundaries],
        "style_examples": list(profile.style_examples),
        "goals": list(profile.goals),
        "persona_baseline": profile.persona_baseline,
        "persona_range": list(profile.persona_range),
        "stance_range": list(profile.stance_range),
    }


def _draft_to_dict(draft: DraftResponse) -> dict[str, Any]:
    data = asdict(draft)
    data["persona_divergence"] = draft.persona_divergence.value
    data["stance_divergence"] = draft.stance_divergence.value
    return data


def _draft_from_dict(data: dict[str, Any]) -> DraftResponse:
    return DraftResponse(
        best_reply=str(data["best_reply"]),
        safer_reply=str(data["safer_reply"]),
        bolder_reply=str(data["bolder_reply"]),
        why_this_works=str(data["why_this_works"]),
        situation_read=str(data["situation_read"]),
        conversation_move=str(data["conversation_move"]),
        hook_source=str(data["hook_source"]),
        naturalness_notes=[str(item) for item in data["naturalness_notes"]],
        followup_if_match_replies=str(data["followup_if_match_replies"]),
        risk_flags=[str(item) for item in data["risk_flags"]],
        missing_info=[str(item) for item in data["missing_info"]],
        mode_notes=str(data["mode_notes"]),
        persona_divergence=Divergence(str(data["persona_divergence"])),
        stance_divergence=Divergence(str(data["stance_divergence"])),
    )


def _draft_review_public_dict(review: DraftReviewDecision) -> dict[str, Any]:
    return {
        "schema_version": review.schema_version,
        "review_id": review.review_id,
        "status": review.status,
        "allowed_for_display": review.allowed_for_display,
        "allowed_for_stage": review.allowed_for_stage,
        "allowed_for_managed_send": review.allowed_for_managed_send,
        "requires_user_confirmation": review.requires_user_confirmation,
        "primary_reason": review.primary_reason,
        "summary": review.summary,
        "findings": [finding.to_dict() for finding in review.findings],
        "revision_hints": list(review.revision_hints),
        "payload_hash": review.payload_hash,
        "payload_format": review.payload_format,
        "message_count": review.message_count,
    }


__all__ = [name for name in globals() if not name.startswith("__")]
