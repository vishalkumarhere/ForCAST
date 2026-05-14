"""
State policy section loader.

Discovers Markdown files in data/state_policies/ and exposes them as a simple
mapping from state name to file content. Filename convention is the state name
lowercased with spaces replaced by hyphens, e.g.:

    data/state_policies/michigan.md
    data/state_policies/new-hampshire.md
    data/state_policies/west-virginia.md

File contents are rendered as standard Markdown by Streamlit.
"""

from __future__ import annotations

from pathlib import Path


def _state_to_filename(state: str) -> str:
    return state.strip().lower().replace(" ", "-") + ".md"


def _filename_to_state(filename: str) -> str:
    stem = Path(filename).stem
    return stem.replace("-", " ").title()


def list_states_with_policies(policy_dir: Path) -> list[str]:
    """Return list of state display names that have a policy file."""
    if not policy_dir.exists():
        return []
    files = [
        f for f in policy_dir.glob("*.md")
        if not f.name.startswith("_")  # skip _README.md and similar
    ]
    return sorted(_filename_to_state(f.name) for f in files)


def load_policy(policy_dir: Path, state: str) -> str | None:
    """Return the Markdown content for a state, or None if no file exists."""
    path = policy_dir / _state_to_filename(state)
    if not path.exists():
        return None
    return path.read_text(encoding="utf-8")
