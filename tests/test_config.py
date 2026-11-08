from __future__ import annotations

import pytest

from buscador.config import ConfigError, load_config


def test_load_config_and_tasks(make_config):
    cfg = make_config()

    assert cfg.origin == "FOR"
    assert cfg.providers["smiles"].window_days == 7
    assert len(cfg.tasks()) == 4
    assert {task.destination for task in cfg.tasks()} == {"GRU", "GIG", "MIA"}
    assert [link.code for link in cfg.enabled_links()] == ["qatar"]


def test_invalid_origin(tmp_path):
    path = tmp_path / "config.yaml"
    path.write_text(
        "origin: FORT\n"
        "destinations:\n  domestic: [GRU]\n"
        "providers:\n  smiles:\n    name: X\n",
        encoding="utf-8",
    )
    with pytest.raises(ConfigError, match="origin"):
        load_config(path)


def test_invalid_destination(tmp_path):
    path = tmp_path / "config.yaml"
    path.write_text(
        "origin: FOR\n"
        "destinations:\n  domestic: [GR]\n"
        "providers:\n  smiles:\n    name: X\n",
        encoding="utf-8",
    )
    with pytest.raises(ConfigError, match="destinations.domestic"):
        load_config(path)


def test_missing_templates_directory(tmp_path):
    path = tmp_path / "config.yaml"
    path.write_text(
        "origin: FOR\n"
        "destinations:\n  domestic: [GRU]\n"
        "paths:\n  templates: nao-existe\n"
        "providers:\n  smiles:\n    name: X\n",
        encoding="utf-8",
    )
    with pytest.raises(ConfigError, match="templates"):
        load_config(path)
