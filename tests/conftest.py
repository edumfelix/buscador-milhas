from __future__ import annotations

from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

import pytest

from buscador.config import AppConfig, load_config

REPO_ROOT = Path(__file__).resolve().parents[1]


@pytest.fixture
def now() -> datetime:
    return datetime(2026, 11, 8, 12, 0, tzinfo=ZoneInfo("America/Fortaleza"))


@pytest.fixture
def make_config(tmp_path: Path):
    def _make() -> AppConfig:
        config_path = tmp_path / "config.yaml"
        data_dir = tmp_path / "data"
        site_dir = tmp_path / "site"
        config_path.write_text(
            f"""
origin: FOR
horizon_days: 180
adults: 1
timezone: America/Fortaleza
cabins:
  domestic: [Y]
  international: [Y, J]
destinations:
  domestic: [GRU, GIG]
  international: [MIA]
paths:
  data: "{data_dir.as_posix()}"
  templates: "{(REPO_ROOT / 'templates').as_posix()}"
  static: "{(REPO_ROOT / 'static').as_posix()}"
  site: "{site_dir.as_posix()}"
coverage:
  hot_destinations: [GRU]
  max_age_hours: 168
  stale_after_hours: 26
alerting:
  new_enabled: true
  drop_min_pct: 10
  drop_min_miles: 1000
  suspicious_drop_pct: 60
  cooldown_hours: 24
  max_items_per_message: 10
  max_messages_per_run: 3
site:
  title: "Teste — Buscador de Milhas"
  max_cards: 100
providers:
  smiles:
    name: "Smiles (Gol)"
    enabled: true
    regions: [domestic, international]
    domestic_cabins: [Y]
    international_cabins: [Y, J]
    window_days: 7
    sale_window_days: 180
    max_requests_per_run: 10
    request_delay_ms: [0, 0]
    timeout_seconds: 5
    deep_link: "https://example.com/smiles"
links:
  qatar:
    name: "Qatar Privilege Club"
    url: "https://example.com/qatar"
    note: "Parceiro de teste"
    enabled: true
""",
            encoding="utf-8",
        )
        return load_config(config_path)

    return _make
