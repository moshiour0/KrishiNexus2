from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from .models import Provenance


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def dataset_record(name: str, prov: Provenance, coverage: str, status: str = "available") -> dict[str, Any]:
    return {
        "name": name,
        "source": prov.source,
        "source_type": prov.source_type,
        "retrieval_date": prov.retrieval_date,
        "spatial_resolution": prov.spatial_resolution,
        "temporal_resolution": prov.temporal_resolution,
        "citation": prov.citation,
        "confidence": prov.confidence,
        "coverage": coverage,
        "status": status,
    }


def provenance_from_dict(d: dict[str, Any]) -> Provenance:
    return Provenance(**d)
