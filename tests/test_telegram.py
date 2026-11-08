from __future__ import annotations

from datetime import date

from buscador.models import Alert, Opportunity
from buscador.telegram import build_digest, format_alert, split_message


def make_opp(
    miles: int = 12000,
    url: str = "https://example.com/?a=1&b=2",
) -> Opportunity:
    return Opportunity(
        provider="smiles",
        origin="FOR",
        destination="GRU",
        depart_date=date(2026, 12, 1),
        cabin="Y",
        miles=miles,
        taxes_brl=34.5,
        booking_url=url,
    )


def test_split_message_respects_limit():
    text = "\n".join(f"linha {index}" for index in range(1000))

    parts = split_message(text, limit=200)

    assert all(len(part) <= 200 for part in parts)
    assert "".join(parts) == text


def test_split_message_handles_long_line():
    text = "x" * 500

    parts = split_message(text, limit=120)

    assert all(len(part) <= 120 for part in parts)
    assert "".join(parts) == text


def test_format_alert_escapes_html(make_config):
    cfg = make_config()

    message = format_alert(Alert("new", make_opp()), cfg)

    assert "Smiles (Gol)" in message
    assert "&amp;" in message
    assert "<script>" not in message


def test_build_digest_has_sections(make_config):
    cfg = make_config()
    new = Alert("new", make_opp())
    drop = Alert(
        "drop",
        make_opp(miles=9000),
        previous_miles=12000,
        drop_pct=25.0,
    )

    messages = build_digest(
        [new, drop], cfg, site_url="https://example.com"
    )

    assert messages
    joined = "\n".join(messages)
    assert "Novas oportunidades" in joined
    assert "Quedas de preço" in joined
    assert "Ver a página" in joined
    assert "25.0%" in joined
