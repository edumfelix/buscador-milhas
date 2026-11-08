from __future__ import annotations

from datetime import date, datetime, timedelta

import pytest

from buscador.config import AppConfig
from buscador.models import Opportunity, ScanOutcome, coverage_key
from buscador.state import State

START = date(2026, 12, 1)
END = date(2026, 12, 7)
HORIZON_END = date(2027, 5, 7)


def make_state(tmp_path) -> State:
    return State(tmp_path / "state.json", tmp_path / "history.jsonl")


def make_opp(
    *,
    provider: str = "smiles",
    destination: str = "GRU",
    cabin: str = "Y",
    depart: date = START,
    miles: int = 20000,
    url: str = "https://example.com/smiles",
) -> Opportunity:
    return Opportunity(
        provider=provider,
        origin="FOR",
        destination=destination,
        depart_date=depart,
        cabin=cabin,  # type: ignore[arg-type]
        miles=miles,
        taxes_brl=50.0,
        flights=["XX 123"],
        stops=0,
        booking_url=url,
    )


def make_outcome(
    opportunities: list[Opportunity],
    *,
    provider: str = "smiles",
    destination: str = "GRU",
    cabin: str = "Y",
    start: date = START,
    end: date = END,
    complete: bool = True,
) -> ScanOutcome:
    return ScanOutcome(
        provider=provider,
        origin="FOR",
        destination=destination,
        cabin=cabin,  # type: ignore[arg-type]
        window_start=start,
        window_end=end,
        opportunities=opportunities,
        complete=complete,
    )


def mark_checked(
    state: State,
    now: datetime,
    *,
    provider: str = "smiles",
    destination: str = "GRU",
    cabin: str = "Y",
    start: date = START,
    end: date = END,
    last_checked: datetime | None = None,
) -> None:
    key = coverage_key(provider, "FOR", destination, cabin)
    state.raw["coverage"][key] = {
        "provider": provider,
        "origin": "FOR",
        "destination": destination,
        "cabin": cabin,
        "window_start": start.isoformat(),
        "window_end": end.isoformat(),
        "checked_dates": [
            (start + timedelta(days=index)).isoformat()
            for index in range((end - start).days + 1)
        ],
        "last_checked_at": (last_checked or now).isoformat(timespec="seconds"),
        "next_start": (end + timedelta(days=1)).isoformat(),
        "status": "ok",
        "error": None,
    }
    state.begin_run(now)


def seed_record(
    state: State,
    now: datetime,
    opportunity: Opportunity,
    *,
    available: bool = True,
) -> None:
    state.raw["opportunities"][opportunity.key] = {
        **opportunity.to_dict(),
        "first_seen": (now - timedelta(days=1)).isoformat(timespec="seconds"),
        "last_seen": (now - timedelta(hours=1)).isoformat(timespec="seconds"),
        "last_checked_at": (now - timedelta(hours=1)).isoformat(
            timespec="seconds"
        ),
        "available": available,
        "lowest_miles": opportunity.miles,
        "below_average": False,
        "suspicious": False,
    }


def apply(
    state: State,
    cfg: AppConfig,
    now: datetime,
    opportunities: list[Opportunity],
    *,
    bootstrap: bool = False,
    complete: bool = True,
):
    outcome = make_outcome(opportunities, complete=complete)
    return state.apply_outcome(
        outcome,
        now,
        cfg,
        bootstrap=bootstrap,
        today=now.date(),
        horizon_end=HORIZON_END,
    )


def test_bootstrap_is_silent(tmp_path, make_config, now):
    state = make_state(tmp_path)
    cfg = make_config()
    state.begin_run(now)

    alerts = apply(state, cfg, now, [make_opp()], bootstrap=True)

    assert alerts == []
    record = state.raw["opportunities"][make_opp().key]
    assert record["miles"] == 20000
    assert record["available"] is True
    state.end_run(now)
    assert state.raw["bootstrap_done"] is True


def test_new_opportunity_alerts_after_previous_check(tmp_path, make_config, now):
    state = make_state(tmp_path)
    cfg = make_config()
    state.raw["bootstrap_done"] = True
    mark_checked(state, now)

    alerts = apply(state, cfg, now, [make_opp()])

    assert [alert.kind for alert in alerts] == ["new"]
    assert alerts[0].opportunity.miles == 20000


def test_new_requires_recent_coverage(tmp_path, make_config, now):
    state = make_state(tmp_path)
    cfg = make_config()
    state.raw["bootstrap_done"] = True
    mark_checked(state, now, last_checked=now - timedelta(days=20))

    alerts = apply(state, cfg, now, [make_opp()])

    assert alerts == []


def test_drop_alert(tmp_path, make_config, now):
    state = make_state(tmp_path)
    cfg = make_config()
    state.raw["bootstrap_done"] = True
    seed_record(state, now, make_opp(miles=20000))
    mark_checked(state, now)

    alerts = apply(state, cfg, now, [make_opp(miles=17000)])

    assert [alert.kind for alert in alerts] == ["drop"]
    assert alerts[0].previous_miles == 20000
    assert alerts[0].drop_pct == pytest.approx(15.0)
    record = state.raw["opportunities"][make_opp().key]
    assert record["miles"] == 17000
    assert record["last_alert_kind"] == "drop"


@pytest.mark.parametrize(
    ("new_miles", "expected_alerts"),
    [(18000, 1), (18020, 0)],
)
def test_drop_threshold_is_exact(
    tmp_path, make_config, now, new_miles, expected_alerts
):
    state = make_state(tmp_path)
    cfg = make_config()
    state.raw["bootstrap_done"] = True
    seed_record(state, now, make_opp(miles=20000))
    mark_checked(state, now)

    alerts = apply(state, cfg, now, [make_opp(miles=new_miles)])

    assert len(alerts) == expected_alerts


def test_cooldown_blocks_duplicate_drop(tmp_path, make_config, now):
    state = make_state(tmp_path)
    cfg = make_config()
    state.raw["bootstrap_done"] = True
    seed_record(state, now, make_opp(miles=20000))
    state.raw["opportunities"][make_opp().key]["last_alert_at"] = (
        now - timedelta(hours=1)
    ).isoformat(timespec="seconds")
    mark_checked(state, now)

    alerts = apply(state, cfg, now, [make_opp(miles=17000)])

    assert alerts == []


def test_suspicious_drop_does_not_alert(tmp_path, make_config, now):
    state = make_state(tmp_path)
    cfg = make_config()
    state.raw["bootstrap_done"] = True
    seed_record(state, now, make_opp(miles=20000))
    mark_checked(state, now)

    alerts = apply(state, cfg, now, [make_opp(miles=5000)])

    assert alerts == []
    record = state.raw["opportunities"][make_opp().key]
    assert record["suspicious"] is True


def test_reappearance_alerts_new(tmp_path, make_config, now):
    state = make_state(tmp_path)
    cfg = make_config()
    state.raw["bootstrap_done"] = True
    seed_record(state, now, make_opp(miles=20000), available=False)
    mark_checked(state, now)

    alerts = apply(state, cfg, now, [make_opp(miles=20000)])

    assert [alert.kind for alert in alerts] == ["new"]
    record = state.raw["opportunities"][make_opp().key]
    assert record["available"] is True


def test_complete_scan_marks_missing_dates_unavailable(
    tmp_path, make_config, now
):
    state = make_state(tmp_path)
    cfg = make_config()
    state.raw["bootstrap_done"] = True
    first = make_opp(depart=START)
    second = make_opp(depart=START + timedelta(days=1))
    seed_record(state, now, first)
    seed_record(state, now, second)
    mark_checked(state, now)

    apply(state, cfg, now, [first])

    assert state.raw["opportunities"][first.key]["available"] is True
    assert state.raw["opportunities"][second.key]["available"] is False


def test_below_average_uses_history(tmp_path, make_config, now):
    state = make_state(tmp_path)
    cfg = make_config()
    state.raw["bootstrap_done"] = True
    for miles in (20000, 21000, 22000, 23000, 24000):
        state.history.append(
            {
                "ts": (now - timedelta(days=10)).isoformat(timespec="seconds"),
                "provider": "smiles",
                "origin": "FOR",
                "destination": "GRU",
                "cabin": "Y",
                "depart_date": START.isoformat(),
                "miles": miles,
            }
        )
    mark_checked(state, now)

    apply(state, cfg, now, [make_opp(miles=15000)])

    assert state.raw["opportunities"][make_opp().key]["below_average"] is True


def test_coverage_next_start_wraps_at_horizon(tmp_path, make_config, now):
    state = make_state(tmp_path)
    cfg = make_config()
    state.begin_run(now)
    start = HORIZON_END - timedelta(days=6)
    opportunity = make_opp(depart=start)
    outcome = make_outcome(
        [opportunity], start=start, end=HORIZON_END
    )

    state.apply_outcome(
        outcome,
        now,
        cfg,
        bootstrap=False,
        today=now.date(),
        horizon_end=HORIZON_END,
    )

    cov = state.raw["coverage"][coverage_key("smiles", "FOR", "GRU", "Y")]
    assert cov["next_start"] == (now.date() + timedelta(days=1)).isoformat()
    assert start.isoformat() in cov["checked_dates"]


def test_partial_scan_keeps_next_start(tmp_path, make_config, now):
    state = make_state(tmp_path)
    cfg = make_config()
    state.raw["bootstrap_done"] = True
    mark_checked(state, now)
    cov_key = coverage_key("smiles", "FOR", "GRU", "Y")
    state.raw["coverage"][cov_key]["next_start"] = START.isoformat()
    state.begin_run(now)

    apply(state, cfg, now, [make_opp()], complete=False)

    cov = state.raw["coverage"][cov_key]
    assert cov["next_start"] == START.isoformat()
    assert cov["status"] == "partial"


def test_save_and_load_roundtrip(tmp_path, make_config, now):
    state = make_state(tmp_path)
    cfg = make_config()
    state.raw["bootstrap_done"] = True
    mark_checked(state, now)
    apply(state, cfg, now, [make_opp()])
    state.end_run(now)
    state.save()

    loaded = State.load(tmp_path)

    assert make_opp().key in loaded.raw["opportunities"]
    assert loaded.raw["bootstrap_done"] is True
    assert loaded.history
