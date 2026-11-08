from __future__ import annotations

from datetime import timedelta

from buscador.render import render_site
from buscador.state import State


def test_render_page(tmp_path, make_config, now):
    cfg = make_config()
    state = State.load(cfg.data_dir)
    state.raw["bootstrap_done"] = True
    state.raw["updated_at"] = now.isoformat(timespec="seconds")
    state.raw["providers"]["smiles"] = {
        "status": "ok",
        "last_success": now.isoformat(timespec="seconds"),
        "requests": 3,
        "navigations": 0,
        "scans": 2,
        "results": 2,
        "error": None,
    }
    key = "smiles|FOR|GRU|2026-12-01|Y"
    state.raw["opportunities"][key] = {
        "provider": "smiles",
        "origin": "FOR",
        "destination": "GRU",
        "depart_date": "2026-12-01",
        "cabin": "Y",
        "miles": 12000,
        "taxes_brl": 34.5,
        "flights": ["G3 1234"],
        "stops": 0,
        "booking_url": "https://example.com/smiles?a=1&b=2",
        "first_seen": (now - timedelta(hours=1)).isoformat(
            timespec="seconds"
        ),
        "last_seen": now.isoformat(timespec="seconds"),
        "last_checked_at": now.isoformat(timespec="seconds"),
        "available": True,
        "lowest_miles": 12000,
        "below_average": True,
        "suspicious": False,
    }

    path = render_site(cfg, state, now)
    html = path.read_text(encoding="utf-8")

    assert "Fortaleza" in html
    assert "12.000" in html
    assert "Smiles (Gol)" in html
    assert "Qatar Privilege Club" in html
    assert "Dados atualizados" in html
    assert "São Paulo (GRU)" in html
    assert 'data-program="smiles"' in html
    assert "Abaixo da média" in html
    assert (cfg.site_dir / "style.css").exists()
    assert (cfg.site_dir / "app.js").exists()
