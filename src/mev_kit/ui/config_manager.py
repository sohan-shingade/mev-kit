"""ConfigManager — TOML config read/write/validate with profile management."""

from __future__ import annotations

import os
from pathlib import Path
from typing import Any

import tomli


class ConfigManager:
    """Manages TOML config files for mev-kit profiles."""

    def __init__(self, config_dir: str) -> None:
        self.config_dir = Path(config_dir)

    def list_profiles(self) -> list[str]:
        """List available config profile names (without .toml extension)."""
        if not self.config_dir.exists():
            return []
        return sorted(p.stem for p in self.config_dir.glob("*.toml"))

    def load(self, profile: str) -> dict[str, Any]:
        """Load a TOML config file by profile name."""
        path = self.config_dir / f"{profile}.toml"
        if not path.exists():
            raise FileNotFoundError(f"Config profile not found: {path}")
        with open(path, "rb") as f:
            return tomli.load(f)

    def save(self, profile: str, data: dict[str, Any]) -> None:
        """Save config data to a TOML file."""
        self.config_dir.mkdir(parents=True, exist_ok=True)
        path = self.config_dir / f"{profile}.toml"
        with open(path, "w") as f:
            _write_toml(f, data)

    def env_key_status(self) -> dict[str, bool]:
        """Return which API keys are set in the environment (never values)."""
        keys = [
            "HELIUS_API_KEY", "HELIUS_RPC_URL", "SOLANA_RPC_URL",
            "JITO_BLOCK_ENGINE_URL", "WALLET_KEYPAIR_PATH",
        ]
        return {k: bool(os.environ.get(k)) for k in keys}


def _write_toml(f: Any, data: dict[str, Any], prefix: str = "") -> None:  # noqa: ANN401
    """Write a nested dict as TOML format."""
    for key, value in data.items():
        if not isinstance(value, dict):
            f.write(f"{key} = {_toml_value(value)}\n")
    for key, value in data.items():
        if isinstance(value, dict):
            section = f"{prefix}{key}" if not prefix else f"{prefix}.{key}"
            f.write(f"\n[{section}]\n")
            for k, v in value.items():
                f.write(f"{k} = {_toml_value(v)}\n")


def _toml_value(v: Any) -> str:  # noqa: ANN401
    """Convert a Python value to TOML string representation."""
    if isinstance(v, bool):
        return "true" if v else "false"
    if isinstance(v, str):
        return f'"{v}"'
    if isinstance(v, (int, float)):
        return str(v)
    if isinstance(v, list):
        items = ", ".join(f'"{i}"' if isinstance(i, str) else str(i) for i in v)
        return f"[{items}]"
    return str(v)
