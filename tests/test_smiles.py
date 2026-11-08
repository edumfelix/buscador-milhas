from __future__ import annotations

from datetime import date
from pathlib import Path

from buscador.providers.base import ScanContext
from buscador.providers.smiles import (
    SmilesProvider,
    filter_for_cabin,
    parse_smiles_response,
)

FIXTURE = Path(__file__).parent / "fixtures" / "smiles_search_200_min.json"
REQUESTED = date(2026, 11, 12)
WINDOW_START = date(2026, 11, 9)
WINDOW_END = date(2026, 11, 15)


def read_fixture() -> str:
    return FIXTURE.read_text(encoding="utf-8")


def test_parse_smiles_response_chooses_club_fare_and_business():
    opportunities, covered = parse_smiles_response(
        read_fixture(),
        origin="FOR",
        destination="GRU",
        requested_date=REQUESTED,
        window_start=WINDOW_START,
        window_end=WINDOW_END,
        booking_url="https://example.com/smiles",
    )

    by_key = {
        (item.depart_date.isoformat(), item.cabin): item
        for item in opportunities
    }
    economy = by_key[("2026-11-12", "Y")]
    assert economy.miles == 12000
    assert economy.taxes_brl == 34.5
    assert economy.flights == ["G3 1234"]
    assert economy.stops == 0

    business = by_key[("2026-11-12", "J")]
    assert business.miles == 40000
    assert business.taxes_brl == 50.0
    assert business.stops == 1
    assert business.flights == ["G3 5678", "G3 9012"]

    calendar_day = by_key[("2026-11-10", "Y")]
    assert calendar_day.miles == 11000
    assert calendar_day.taxes_brl is None
    assert calendar_day.stops is None

    assert date(2026, 11, 10) in covered
    assert REQUESTED in covered
    assert date(2026, 11, 15) not in covered


def test_parse_smiles_response_empty_segment():
    opportunities, covered = parse_smiles_response(
        '{"requestedFlightSegmentList": []}',
        origin="FOR",
        destination="GRU",
        requested_date=REQUESTED,
        window_start=WINDOW_START,
        window_end=WINDOW_END,
        booking_url="https://example.com/smiles",
    )

    assert opportunities == []
    assert covered == [REQUESTED]


def test_filter_for_cabin_business_only_covers_detail_day():
    opportunities, covered = parse_smiles_response(
        read_fixture(),
        origin="FOR",
        destination="GRU",
        requested_date=REQUESTED,
        window_start=WINDOW_START,
        window_end=WINDOW_END,
        booking_url="https://example.com/smiles",
    )

    economy, economy_covered = filter_for_cabin(
        opportunities, covered, "Y", REQUESTED
    )
    business, business_covered = filter_for_cabin(
        opportunities, covered, "J", REQUESTED
    )

    assert {item.cabin for item in economy} == {"Y"}
    assert date(2026, 11, 10) in economy_covered
    assert {item.cabin for item in business} == {"J"}
    assert business_covered == [REQUESTED]


class FakePage:
    def __init__(self, text: str) -> None:
        self.text = text
        self.calls = 0

    def evaluate(self, script: str, payload: dict) -> dict:
        self.calls += 1
        return {"status": 200, "text": self.text}


def test_provider_caches_response_between_cabins(make_config, now):
    cfg = make_config()
    provider = SmilesProvider("smiles", cfg.providers["smiles"], cfg)
    provider._page = FakePage(read_fixture())
    context = ScanContext(
        origin="FOR", adults=1, now=now, timeout_seconds=5
    )

    economy = provider.scan(
        "GRU", "Y", WINDOW_START, WINDOW_END, context
    )
    business = provider.scan(
        "GRU", "J", WINDOW_START, WINDOW_END, context
    )

    assert provider._page.calls == 1
    assert provider.requests == 1
    assert {item.cabin for item in economy.opportunities} == {"Y"}
    assert all(
        "originAirport=FOR" in item.booking_url
        for item in economy.opportunities
    )
    assert economy.covered_dates is not None
    assert date(2026, 11, 10) in economy.covered_dates
    assert {item.cabin for item in business.opportunities} == {"J"}
    assert business.covered_dates == [REQUESTED]
