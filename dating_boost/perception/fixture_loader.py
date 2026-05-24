from __future__ import annotations

import json
from pathlib import Path

from dating_boost.perception.observations import AppObservation


def load_observation(path: Path) -> AppObservation:
    return AppObservation.from_dict(json.loads(path.read_text(encoding="utf-8")))
