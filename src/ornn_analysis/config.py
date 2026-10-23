"""Paths and .env settings."""
import os
from pathlib import Path

from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parents[2]
load_dotenv(ROOT / ".env")

CACHE_DIR = ROOT / "data" / "cache"
EVENTS_FILE = ROOT / "data" / "events.csv"


def env(name: str) -> str | None:
    """Environment variable, with empty strings treated as unset."""
    return os.getenv(name) or None
