"""Immutable raw storage with an append-only JSONL manifest.

Every provider response is written once, content-addressed by SHA-256, together with
the query parameters (never secrets), retrieval time and licence reference, so any
derived table can be traced back to the exact bytes it came from.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from threading import Lock

from gridmind.config import RAW_DIR

_LOCK = Lock()
SECRET_KEYS = {"securityToken", "api_key", "apikey", "token"}


@dataclass(frozen=True)
class RawRecord:
    source: str
    dataset: str
    params: dict
    sha256: str
    path: str
    retrieved_at_utc: str
    licence: str
    bytes: int
    extra: dict = field(default_factory=dict)


def _clean(params: dict) -> dict:
    return {k: v for k, v in params.items() if k not in SECRET_KEYS}


def store_raw(
    content: bytes,
    *,
    source: str,
    dataset: str,
    params: dict,
    licence: str,
    suffix: str,
    raw_dir: Path = RAW_DIR,
    extra: dict | None = None,
) -> RawRecord:
    digest = hashlib.sha256(content).hexdigest()
    folder = raw_dir / source / dataset
    folder.mkdir(parents=True, exist_ok=True)
    path = folder / f"{digest}{suffix}"
    if not path.exists():
        path.write_bytes(content)
    rec = RawRecord(
        source=source,
        dataset=dataset,
        params=_clean(params),
        sha256=digest,
        path=str(path.relative_to(raw_dir)),
        retrieved_at_utc=datetime.now(timezone.utc).isoformat(timespec="seconds"),
        licence=licence,
        bytes=len(content),
        extra=extra or {},
    )
    with _LOCK, (raw_dir / "manifest.jsonl").open("a") as f:
        f.write(json.dumps(asdict(rec), default=str) + "\n")
    return rec


def read_manifest(raw_dir: Path = RAW_DIR) -> list[dict]:
    p = raw_dir / "manifest.jsonl"
    if not p.exists():
        return []
    return [json.loads(line) for line in p.read_text().splitlines() if line.strip()]
