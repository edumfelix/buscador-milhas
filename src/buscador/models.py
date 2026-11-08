from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, datetime
from typing import Any, Literal

Cabin = Literal["Y", "J"]
CABINS: tuple[Cabin, ...] = ("Y", "J")
CABIN_LABELS: dict[str, str] = {"Y": "Econômica", "J": "Executiva"}
ProviderStatus = Literal[
    "ok",
    "partial",
    "blocked",
    "error",
    "not_implemented",
    "disabled",
]
AlertKind = Literal["new", "drop"]


def opportunity_key(
    provider: str,
    origin: str,
    destination: str,
    depart_date: date | str,
    cabin: str,
) -> str:
    date_str = depart_date.isoformat() if isinstance(depart_date, date) else str(depart_date)
    return f"{provider}|{origin}|{destination}|{date_str}|{cabin}"


def coverage_key(provider: str, origin: str, destination: str, cabin: str) -> str:
    return f"{provider}|{origin}|{destination}|{cabin}"


@dataclass(frozen=True)
class SearchQuery:
    provider: str
    origin: str
    destination: str
    depart_date: date
    cabin: Cabin
    adults: int = 1


@dataclass
class Opportunity:
    provider: str
    origin: str
    destination: str
    depart_date: date
    cabin: Cabin
    miles: int
    taxes_brl: float | None = None
    flights: list[str] = field(default_factory=list)
    stops: int | None = None
    booking_url: str = ""
    fetched_at: datetime | None = None

    @property
    def key(self) -> str:
        return opportunity_key(
            self.provider,
            self.origin,
            self.destination,
            self.depart_date,
            self.cabin,
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "provider": self.provider,
            "origin": self.origin,
            "destination": self.destination,
            "depart_date": self.depart_date.isoformat(),
            "cabin": self.cabin,
            "miles": int(self.miles),
            "taxes_brl": self.taxes_brl,
            "flights": list(self.flights),
            "stops": self.stops,
            "booking_url": self.booking_url,
            "fetched_at": self.fetched_at.isoformat() if self.fetched_at else None,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> Opportunity:
        fetched_raw = data.get("fetched_at")
        return cls(
            provider=str(data["provider"]),
            origin=str(data["origin"]),
            destination=str(data["destination"]),
            depart_date=date.fromisoformat(str(data["depart_date"])),
            cabin=str(data["cabin"]),  # type: ignore[arg-type]
            miles=int(data["miles"]),
            taxes_brl=(
                float(data["taxes_brl"]) if data.get("taxes_brl") is not None else None
            ),
            flights=[str(item) for item in data.get("flights") or []],
            stops=int(data["stops"]) if data.get("stops") is not None else None,
            booking_url=str(data.get("booking_url") or ""),
            fetched_at=datetime.fromisoformat(str(fetched_raw)) if fetched_raw else None,
        )


@dataclass
class ScanOutcome:
    provider: str
    origin: str
    destination: str
    cabin: Cabin
    window_start: date
    window_end: date
    opportunities: list[Opportunity] = field(default_factory=list)
    complete: bool = True
    error: str | None = None
    covered_dates: list[date] | None = None

    @property
    def coverage_key(self) -> str:
        return coverage_key(self.provider, self.origin, self.destination, self.cabin)


@dataclass
class Alert:
    kind: AlertKind
    opportunity: Opportunity
    previous_miles: int | None = None
    drop_pct: float | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "kind": self.kind,
            "key": self.opportunity.key,
            "destination": self.opportunity.destination,
            "depart_date": self.opportunity.depart_date.isoformat(),
            "cabin": self.opportunity.cabin,
            "provider": self.opportunity.provider,
            "miles": self.opportunity.miles,
            "previous_miles": self.previous_miles,
            "drop_pct": self.drop_pct,
            "booking_url": self.opportunity.booking_url,
        }


@dataclass
class ProviderRun:
    provider: str
    status: ProviderStatus
    started_at: datetime
    finished_at: datetime | None = None
    requests: int = 0
    navigations: int = 0
    results: int = 0
    scans: int = 0
    error: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "provider": self.provider,
            "status": self.status,
            "started_at": self.started_at.isoformat(),
            "finished_at": self.finished_at.isoformat() if self.finished_at else None,
            "requests": self.requests,
            "navigations": self.navigations,
            "results": self.results,
            "scans": self.scans,
            "error": self.error,
        }


@dataclass
class RunResult:
    alerts: list[Alert] = field(default_factory=list)
    provider_runs: dict[str, ProviderRun] = field(default_factory=dict)
    rendered_path: str | None = None
    messages_sent: int = 0
