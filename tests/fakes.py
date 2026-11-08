from __future__ import annotations

from datetime import date

from buscador.deeplinks import build_booking_url
from buscador.models import Opportunity, ScanOutcome
from buscador.providers.base import BaseProvider, ScanContext


class FakeProvider(BaseProvider):
    def __init__(
        self,
        code: str,
        config,
        app,
        prices: list[int],
    ) -> None:
        super().__init__(code, config, app)
        self.prices = list(prices)
        self.calls = 0

    def scan(
        self,
        destination: str,
        cabin: str,
        window_start: date,
        window_end: date,
        ctx: ScanContext,
    ) -> ScanOutcome:
        price = self.prices[min(self.calls, len(self.prices) - 1)]
        self.calls += 1
        self.requests += 1
        booking_url = build_booking_url(
            self.code,
            ctx.origin,
            destination,
            window_start,
            cabin,
            self.app.adults,
            self.config.deep_link,
        )
        opportunity = Opportunity(
            provider=self.code,
            origin=ctx.origin,
            destination=destination,
            depart_date=window_start,
            cabin=cabin,  # type: ignore[arg-type]
            miles=price,
            taxes_brl=50.0,
            flights=["XX 123"],
            stops=0,
            booking_url=booking_url,
            fetched_at=ctx.now,
        )
        return ScanOutcome(
            provider=self.code,
            origin=ctx.origin,
            destination=destination,
            cabin=cabin,  # type: ignore[arg-type]
            window_start=window_start,
            window_end=window_end,
            opportunities=[opportunity],
            complete=True,
        )
