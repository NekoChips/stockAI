"""Web static assets and HTML rendering."""

from __future__ import annotations

from pathlib import Path

_PACKAGE_DIR = Path(__file__).resolve().parent


def spa_root() -> Path:
    return _PACKAGE_DIR / "spa"


def render_spa_index() -> str:
    index = spa_root() / "index.html"
    if not index.is_file():
        raise FileNotFoundError(f"SPA index missing: {index}")
    return index.read_text(encoding="utf-8")


def resolve_spa_file(url_path: str) -> Path | None:
    """Map URL path to a file under spa_root. Reject path traversal."""
    raw = url_path.split("?", 1)[0]
    if raw in {"/", ""}:
        return None
    relative = raw.lstrip("/")
    if not relative or relative.endswith("/"):
        return None
    root = spa_root().resolve()
    candidate = (root / relative).resolve()
    try:
        candidate.relative_to(root)
    except ValueError:
        return None
    if not candidate.is_file():
        return None
    return candidate
