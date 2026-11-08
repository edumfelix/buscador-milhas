from __future__ import annotations

from datetime import UTC, date, datetime

from buscador.deeplinks import (
    build_azul_url,
    build_booking_url,
    build_smiles_url,
    roundtrip_urls,
    roundtrip_verified,
    search_copy_text,
)
from buscador.models import Opportunity


def test_azul_url_keeps_raw_brackets_and_mdy():
    url = build_azul_url("FOR", "GRU", date(2026, 12, 1))

    assert url.startswith(
        "https://www.voeazul.com.br/br/pt/home/selecao-voo?"
    )
    assert "c[0].ds=FOR" in url
    assert "c[0].std=12/1/2026" in url
    assert "c[0].as=GRU" in url
    assert "cc=PTS" in url
    assert "%5B" not in url


def test_azul_roundtrip_url():
    url = build_azul_url(
        "FOR", "GRU", date(2026, 12, 1), return_date=date(2026, 12, 8)
    )

    assert "c[1].ds=GRU" in url
    assert "c[1].std=12/8/2026" in url
    assert "c[1].as=FOR" in url


def test_smiles_url_has_search_params():
    url = build_smiles_url("FOR", "GRU", date(2026, 12, 1))
    departure_ms = int(
        datetime(2026, 12, 1, 12, tzinfo=UTC).timestamp() * 1000
    )

    assert url.startswith(
        "https://www.smiles.com.br/mfe/emissao-passagem/?"
    )
    assert "originAirport=FOR" in url
    assert "destinationAirport=GRU" in url
    assert "cabin=ALL" in url
    assert "tripType=2" in url
    assert f"departureDate={departure_ms}" in url


def test_roundtrip_urls_have_three_offsets():
    urls = roundtrip_urls(
        "azul",
        "FOR",
        "GRU",
        date(2026, 12, 1),
        "Y",
        1,
        "",
    )

    assert sorted(urls) == [7, 14, 21]
    assert all("c[1].std" in url for url in urls.values())


def test_roundtrip_verified():
    assert roundtrip_verified("azul") is True
    assert roundtrip_verified("smiles") is False


def test_booking_url_falls_back_to_deep_link_for_unknown_provider():
    assert (
        build_booking_url(
            "outro",
            "FOR",
            "GRU",
            date(2026, 12, 1),
            deep_link="https://example.com/outro",
        )
        == "https://example.com/outro"
    )


def test_booking_url_builds_smiles_search():
    url = build_booking_url(
        "smiles",
        "FOR",
        "GRU",
        date(2026, 12, 1),
        deep_link="https://example.com/smiles",
    )

    assert "originAirport=FOR" in url
    assert "destinationAirport=GRU" in url


def test_copy_text():
    opportunity = Opportunity(
        provider="smiles",
        origin="FOR",
        destination="GRU",
        depart_date=date(2026, 12, 1),
        cabin="Y",
        miles=12000,
    )

    text = search_copy_text(opportunity, "Smiles (Gol)")

    assert "FOR → GRU" in text
    assert "01/12/2026" in text
    assert "Econômica" in text
    assert "Smiles (Gol)" in text
