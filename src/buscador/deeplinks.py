from __future__ import annotations

from datetime import UTC, date, datetime, time, timedelta
from urllib.parse import urlencode

from .models import CABIN_LABELS, Opportunity

AZUL_BASE = "https://www.voeazul.com.br/br/pt/home/selecao-voo"
SMILES_BASE = "https://www.smiles.com.br/mfe/emissao-passagem/"
ROUNDTRIP_OFFSETS = (7, 14, 21)


def format_mdY(value: date) -> str:
    """Formato usado pela Azul no deep link: M/D/YYYY, com barras cruas."""
    return f"{value.month}/{value.day}/{value.year}"


def format_date_br(value: date) -> str:
    return value.strftime("%d/%m/%Y")


def build_azul_url(
    origin: str,
    destination: str,
    depart: date,
    cabin: str = "Y",
    adults: int = 1,
    return_date: date | None = None,
) -> str:
    parts = [
        f"c[0].ds={origin}",
        f"c[0].std={format_mdY(depart)}",
        f"c[0].as={destination}",
        "p[0].t=ADT",
        f"p[0].c={adults}",
        "p[0].cp=false",
        "f.dl=3",
        "f.dr=3",
        "cc=PTS",
    ]
    if return_date is not None:
        parts.extend(
            [
                f"c[1].ds={destination}",
                f"c[1].std={format_mdY(return_date)}",
                f"c[1].as={origin}",
            ]
        )
    return f"{AZUL_BASE}?{'&'.join(parts)}"


def build_smiles_url(
    origin: str,
    destination: str,
    depart: date,
    cabin: str = "Y",
    adults: int = 1,
    return_date: date | None = None,
) -> str:
    """Busca de ida no site do Smiles (parâmetros validados no recon).

    O site usa `cabin=ALL` e `tripType=2` (ida). O retorno sugerido não é
    codificado: a página abre a busca de ida e o usuário ajusta a volta.
    """
    departure_ms = int(
        datetime.combine(depart, time(12, 0), tzinfo=UTC).timestamp() * 1000
    )
    query = urlencode(
        {
            "adults": str(adults),
            "cabin": "ALL",
            "children": "0",
            "departureDate": str(departure_ms),
            "infants": "0",
            "tripType": "2",
            "originAirport": origin.upper(),
            "destinationAirport": destination.upper(),
        }
    )
    return f"{SMILES_BASE}?{query}"


def build_booking_url(
    provider_code: str,
    origin: str,
    destination: str,
    depart: date,
    cabin: str = "Y",
    adults: int = 1,
    deep_link: str = "",
    return_date: date | None = None,
) -> str:
    if provider_code == "azul":
        return build_azul_url(
            origin, destination, depart, cabin, adults, return_date
        )
    if provider_code == "smiles":
        return build_smiles_url(
            origin, destination, depart, cabin, adults, return_date
        )
    return deep_link


def roundtrip_urls(
    provider_code: str,
    origin: str,
    destination: str,
    depart: date,
    cabin: str,
    adults: int,
    deep_link: str,
) -> dict[int, str]:
    return {
        days: build_booking_url(
            provider_code,
            origin,
            destination,
            depart,
            cabin,
            adults,
            deep_link,
            return_date=depart + timedelta(days=days),
        )
        for days in ROUNDTRIP_OFFSETS
    }


def roundtrip_verified(provider_code: str) -> bool:
    return provider_code == "azul"


def search_copy_text(opportunity: Opportunity, program_name: str) -> str:
    cabin = CABIN_LABELS.get(opportunity.cabin, opportunity.cabin)
    return (
        f"{opportunity.origin} → {opportunity.destination}, "
        f"{format_date_br(opportunity.depart_date)}, 1 adulto, {cabin} · "
        f"{program_name}"
    )
