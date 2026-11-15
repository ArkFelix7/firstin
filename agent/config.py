"""Shared paths + env for the FirstIn agent server."""
from __future__ import annotations

import os
from pathlib import Path

from dotenv import load_dotenv

AGENT_DIR = Path(__file__).resolve().parent
ROOT = AGENT_DIR.parent
load_dotenv(ROOT / ".env")

CACHE_DIR = AGENT_DIR / "cache"
OUT_DIR = Path(os.environ.get("FIRSTIN_OUT_DIR", AGENT_DIR / "out"))
PROMPTS_DIR = AGENT_DIR / "prompts"
VISION_CACHE_DIR = CACHE_DIR / "vision"
REGISTRY_PATH = Path(os.environ.get("FIRSTIN_REGISTRY", CACHE_DIR / "buildings.json"))
HAZARDS_YAML = AGENT_DIR / "hazards.yaml"


def _resolve(p: str | None, default: Path) -> Path:
    if not p:
        return default
    path = Path(p)
    return path if path.is_absolute() else (ROOT / path).resolve()


def costar_data_dir() -> Path:
    return _resolve(os.environ.get("COSTAR_DATA_DIR"), AGENT_DIR / "data" / "costar")


def model_name() -> str:
    return os.environ.get("FIRSTIN_MODEL", "anthropic:claude-sonnet-5-5")


def vision_model_name() -> str:
    m = os.environ.get("FIRSTIN_VISION_MODEL") or model_name()
    return m.split(":", 1)[1] if ":" in m else m


def has_api_key() -> bool:
    return bool(os.environ.get("ANTHROPIC_API_KEY", "").strip())


def offline_mode() -> bool:
    """Deterministic pipeline when no key or FIRSTIN_OFFLINE=1."""
    return os.environ.get("FIRSTIN_OFFLINE", "") in ("1", "true", "yes") or not has_api_key()


def pace() -> float:
    """Multiplier for offline-mode sleeps (0 = instant, used by tests)."""
    try:
        return float(os.environ.get("FIRSTIN_PACE", "1"))
    except ValueError:
        return 1.0


def unit_name() -> str:
    return os.environ.get("FIRSTIN_UNIT", "Engine 12")


def static_url(path: str | Path | None) -> str | None:
    """Map a local file under agent/cache or agent/out to its served URL."""
    if not path:
        return None
    p = Path(path).resolve()
    for base, prefix in ((CACHE_DIR.resolve(), "/static/cache"), (OUT_DIR.resolve(), "/static/out")):
        try:
            return f"{prefix}/{p.relative_to(base).as_posix()}"
        except ValueError:
            continue
    return None
