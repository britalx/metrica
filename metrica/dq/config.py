"""DQ framework configuration loader."""

from __future__ import annotations

from pathlib import Path

import yaml

from metrica.dq.models import DQConfig


DEFAULT_CONFIG = DQConfig()


def load_dq_config(config_path: Path | None = None) -> DQConfig:
    if config_path and config_path.exists():
        with open(config_path) as f:
            raw = yaml.safe_load(f)
        return DQConfig(**raw)
    return DEFAULT_CONFIG
