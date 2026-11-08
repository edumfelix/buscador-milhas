from __future__ import annotations

from dataclasses import replace
from datetime import timedelta

from buscador.models import coverage_key
from buscador.providers import build_provider
from buscador.runner import RunOptions, run_once
from buscador.state import State
from tests.fakes import FakeProvider


def test_run_pipeline_and_price_drop(tmp_path, make_config, now):
    cfg = make_config()
    first_provider = FakeProvider(
        "smiles", cfg.providers["smiles"], cfg, [20000]
    )

    first = run_once(
        cfg,
        {"smiles": first_provider},
        now=now,
        options=RunOptions(max_units=4, render=True, send_alerts=False),
    )

    assert first.alerts == []
    assert first.rendered_path
    state = State.load(cfg.data_dir)
    assert state.raw["bootstrap_done"] is True
    assert len(state.raw["opportunities"]) == 4

    cov_key = coverage_key("smiles", "FOR", "GRU", "Y")
    state.raw["coverage"][cov_key]["next_start"] = (
        now.date() + timedelta(days=1)
    ).isoformat()
    sent: list = []
    second_provider = FakeProvider(
        "smiles", cfg.providers["smiles"], cfg, [17000]
    )

    second = run_once(
        cfg,
        {"smiles": second_provider},
        now=now,
        options=RunOptions(max_units=4, render=False, send_alerts=True),
        state=state,
        alert_sender=lambda alerts: (sent.extend(alerts) or len(alerts)),
    )

    assert any(alert.kind == "drop" for alert in second.alerts)
    assert sent
    assert second.messages_sent == len(sent)
    assert (
        state.raw["opportunities"]["smiles|FOR|GRU|2026-11-09|Y"][
            "last_alert_kind"
        ]
        == "drop"
    )


def test_fake_block_marks_provider_blocked(tmp_path, make_config, now):
    cfg = make_config()
    provider = FakeProvider("smiles", cfg.providers["smiles"], cfg, [20000])

    result = run_once(
        cfg,
        {"smiles": provider},
        now=now,
        options=RunOptions(
            max_units=2, render=True, fake_block="smiles"
        ),
    )

    assert result.provider_runs["smiles"].status == "blocked"
    state = State.load(cfg.data_dir)
    assert state.raw["providers"]["smiles"]["status"] == "blocked"
    assert result.rendered_path


def test_not_implemented_provider_still_renders(tmp_path, make_config, now):
    cfg = make_config()
    outro = replace(
        cfg.providers["smiles"],
        code="outro",
        name="Outro",
        max_requests_per_run=2,
    )
    cfg.providers["outro"] = outro
    provider = build_provider("outro", outro, cfg)

    result = run_once(
        cfg,
        {"outro": provider},
        now=now,
        options=RunOptions(max_units=2, render=True),
    )

    assert result.provider_runs["outro"].status == "not_implemented"
    assert result.rendered_path
    state = State.load(cfg.data_dir)
    assert state.raw["providers"]["outro"]["status"] == "not_implemented"
