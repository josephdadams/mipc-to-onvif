"""Config loader — reads config.yml."""

from pathlib import Path
import yaml


def load(path: str = "/app/config.yml") -> dict:
    p = Path(path)
    if not p.exists():
        # Fall back to local path for development
        p = Path(__file__).parent.parent / "config.yml"
    with open(p) as f:
        return yaml.safe_load(f)
