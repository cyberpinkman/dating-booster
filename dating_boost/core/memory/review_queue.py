from __future__ import annotations

import hashlib
import os
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from dating_boost.core.storage import JsonStorage


_REVIEW_QUEUE_PATH = Path("memory") / "review_queue.jsonl"


@dataclass
class ReviewItem:
    review_item_id: str
    session_id: str
    match_id: str
    observation_id: str | None
    proposal: dict[str, Any]
    status: str
    created_at: str
    reported_at: str | None
    reviewed_at: str | None
    dedupe_key: str
    source: str
    risk: str

    def __post_init__(self) -> None:
        self.session_id = str(self.session_id or "manual")
        self.proposal = dict(self.proposal)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> ReviewItem:
        return cls(
            review_item_id=str(data["review_item_id"]),
            session_id=str(data.get("session_id") or "manual"),
            match_id=str(data["match_id"]),
            observation_id=data.get("observation_id"),
            proposal=dict(data["proposal"]),
            status=str(data["status"]),
            created_at=str(data["created_at"]),
            reported_at=data.get("reported_at"),
            reviewed_at=data.get("reviewed_at"),
            dedupe_key=str(data["dedupe_key"]),
            source=str(data["source"]),
            risk=str(data["risk"]),
        )


def build_dedupe_key(
    match_id: str,
    action: str,
    normalized_key: str | None,
    normalized_value: str | None,
    observation_id: str | None,
) -> str:
    raw = "|".join([
        match_id,
        action,
        normalized_key or "",
        normalized_value or "",
        observation_id or "",
    ])
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


class ReviewQueueRepository:
    def __init__(self, root: Path):
        self._storage = JsonStorage(root)

    def enqueue(self, item: ReviewItem) -> ReviewItem:
        existing = self.load_items(match_id=item.match_id, status="pending")
        for candidate in existing:
            if candidate.dedupe_key == item.dedupe_key:
                return candidate
        self._storage.append_jsonl(_REVIEW_QUEUE_PATH, item.to_dict())
        return item

    def load_items(
        self,
        *,
        match_id: str | None = None,
        session_id: str | None = None,
        status: str | None = None,
    ) -> list[ReviewItem]:
        items = [
            ReviewItem.from_dict(row)
            for row in self._storage.read_jsonl(_REVIEW_QUEUE_PATH)
        ]
        if match_id is not None:
            items = [item for item in items if item.match_id == match_id]
        if session_id is not None:
            items = [item for item in items if item.session_id == session_id]
        if status is not None:
            items = [item for item in items if item.status == status]
        return items

    def update_status(self, review_item_id: str, status: str) -> ReviewItem:
        items = self.load_items()
        found = False
        updated_item: ReviewItem | None = None
        for item in items:
            if item.review_item_id == review_item_id:
                item.status = status
                item.reviewed_at = datetime.now(timezone.utc).isoformat()
                found = True
                updated_item = item
                break
        if not found:
            raise ValueError(f"review item not found: {review_item_id}")
        self._storage.write_jsonl(_REVIEW_QUEUE_PATH, [item.to_dict() for item in items])
        return updated_item

    def pending_count(self, *, session_id: str | None = None) -> int:
        return len(self.load_items(status="pending", session_id=session_id))

    def has_pending(self, *, session_id: str | None = None) -> bool:
        return self.pending_count(session_id=session_id) > 0

    def delete_items_for_match(self, match_id: str) -> int:
        items = self.load_items()
        remaining = [item for item in items if item.match_id != match_id]
        deleted_count = len(items) - len(remaining)
        if deleted_count > 0:
            self._storage.write_jsonl(_REVIEW_QUEUE_PATH, [item.to_dict() for item in remaining])
        return deleted_count

    def reject_dedupe_key_exists(self, dedupe_key: str) -> bool:
        items = self.load_items(status="rejected")
        return any(item.dedupe_key == dedupe_key for item in items)
