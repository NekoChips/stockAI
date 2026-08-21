"""Web static assets and HTML rendering."""

from pathlib import Path


def render_dashboard_html() -> str:
    """Load the bundled dashboard without coupling it to HTTP routing."""
    return Path(__file__).with_name("dashboard.html").read_text(encoding="utf-8")
