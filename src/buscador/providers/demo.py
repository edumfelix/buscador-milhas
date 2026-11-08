from __future__ import annotations

import hashlib
from datetime import date, timedelta

from ..deeplinks import build_booking_url
from ..models import Opportunity, ScanOutcome
from .base import BaseProvider, ScanContext


def _seed(*parts: object) -> int:
    digest = hashlib.sha256("|".join(map(str, parts)).encode("utf-8")).hexdigest()
    return int(digest[:12], 16)


class DemoProvider(BaseProvider):
    """Gera oportunidades determinísticas para validar o pipeline sem rede."""

    def scan(
        self,
        destination: str,
        cabin: str,
        window_start: date,
        window_end: date,
        ctx: ScanContext,
    ) -> ScanOutcome:
        self.requests += 1
        days = (window_end - window_start).days + 1
        offsets = {0, max(0, days // 2)}
        if days > 3:
            offsets.add(min(days - 1, 2))
        opportunities: list[Opportunity] = []
        for offset in sorted(offsets):
            depart = window_start + timedelta(days=offset)
            if depart > window_end:
                continue
            seed = _seed(self.code, destination, cabin, depart.isoformat())
            domestic = destination in self.app.destinations["domestic"]
            if cabin == "J":
                miles = 60000 + seed % 90000
            elif domestic:
                miles = 8000 + seed % 17000
            else:
                miles = 25000 + seed % 35000
            taxes = round(20 + (seed % 15000) / 100, 2)
            carrier = "G3" if self.code == "smiles" else "AD"
            flight = f"{carrier} {1000 + seed % 8999}"
            booking_url = build_booking_url(
                self.code,
                ctx.origin,
                destination,
                depart,
                cabin,
                self.app.adults,
                self.config.deep_link,
            )
            opportunities.append(
                Opportunity(
                    provider=self.code,
                    origin=ctx.origin,
                    destination=destination,
                    depart_date=depart,
                    cabin=cabin,  # type: ignore[arg-type]
                    miles=miles,
                    taxes_brl=taxes,
                    flights=[flight],
                    stops=0 if seed % 3 else 1,
                    booking_url=booking_url,
                    fetched_at=ctx.now,
                )
            )
        return ScanOutcome(
            provider=self.code,
            origin=ctx.origin,
            destination=destination,
            cabin=cabin,  # type: ignore[arg-type]
            window_start=window_start,
            window_end=window_end,
            opportunities=opportunities,
            complete=True,
        )
