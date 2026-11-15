"""Repository-mining pipeline for the deepfake ethics & gender MSR study."""
from __future__ import annotations

import hashlib
import json
import os
import re
from datetime import datetime, timezone
from functools import lru_cache
from pathlib import Path
from typing import Any

import yaml
from rich.console import Console

ROOT = Path(__file__).resolve().parent.parent
CONFIG_PATH = Path(__file__).resolve().parent / "config.yaml"
console = Console()

PRELIM = "PRELIMINARY – automatic, unverified"


@lru_cache(maxsize=1)
def cfg() -> dict[str, Any]:
    """Load config.yaml (cached for the process)."""
    return yaml.safe_load(CONFIG_PATH.read_text())


def config_hash() -> str:
    return hashlib.sha256(CONFIG_PATH.read_bytes()).hexdigest()[:12]


def out(*parts: str) -> Path:
    """Path under output/, parents created."""
    p = ROOT / cfg()["paths"]["output"] / Path(*parts)
    p.parent.mkdir(parents=True, exist_ok=True)
    return p


def data(*parts: str) -> Path:
    p = ROOT / cfg()["paths"]["data"] / Path(*parts)
    p.parent.mkdir(parents=True, exist_ok=True)
    return p


def slug(full_name: str) -> str:
    """owner/name -> owner__name (filesystem-safe)."""
    return full_name.replace("/", "__")


def snapshot(refresh: bool = False) -> dict[str, str]:
    """Snapshot metadata, created once on the first search run (UTC)."""
    p = out("snapshot.json")
    if p.exists() and not refresh:
        return json.loads(p.read_text())
    snap = {"snapshot_utc": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"), "config_hash": config_hash()}
    p.write_text(json.dumps(snap, indent=2))
    return snap


def pseudonymise(login: str | None) -> str:
    """Stable pseudonym `user_<sha256(salt+login)[:8]>`; the login itself is never stored."""
    if not login:
        return "user_unknown"
    salt = os.environ.get("PSEUDONYM_SALT", cfg()["privacy"]["pseudonym_salt"])
    return "user_" + hashlib.sha256((salt + login.lower()).encode()).hexdigest()[:8]


_MENTION = re.compile(r"(?<![\w.])@[A-Za-z0-9](?:[A-Za-z0-9-]{0,38})")
_EMAIL = re.compile(r"[\w.+-]+@[\w-]+\.[\w.-]+")


def scrub(text: str | None) -> str:
    """Remove e-mail addresses and @handles from free text."""
    return _MENTION.sub("@user", _EMAIL.sub("<email>", text or ""))


def write_json(path: Path, obj: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(obj, indent=2, ensure_ascii=False, default=str))


def read_json(path: Path, default: Any = None) -> Any:
    return json.loads(path.read_text()) if path.exists() else default


def need(path: Path, stage: str) -> Path:
    """Fail with a clear message if an upstream stage output is missing."""
    if not path.exists():
        raise SystemExit(f"Missing {path.relative_to(ROOT)} - run `python -m mining {stage}` first.")
    return path
