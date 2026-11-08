from __future__ import annotations

import json
import logging
import os
from datetime import date, timedelta
from urllib.parse import urlencode

from ..deeplinks import build_booking_url
from ..models import Cabin, Opportunity, ScanOutcome
from .base import (
    BaseProvider,
    ProviderBlocked,
    ProviderError,
    ProviderNotImplemented,
    ScanContext,
)

logger = logging.getLogger(__name__)

API_HOST = "https://api-air-flightsearch-prd.smiles.com.br"
# Chave pública do site (app id), não é credencial de conta. Pode ser
# sobrescrita por SMILES_API_KEY se o valor mudar.
DEFAULT_API_KEY = "aJqPU7xNHl9qN3NVZnPaJ208aPo2Bh2p2ZV844tw"
CABIN_BY_CODE = {
    "ECONOMIC": "Y",
    "BUSINESS": "J",
    "FIRST_CLASS": "J",
}
FARE_ORDER = ("SMILES_CLUB", "SMILES")


def _parse_date(value: object) -> date | None:
    if not value:
        return None
    try:
        return date.fromisoformat(str(value)[:10])
    except ValueError:
        return None


def _as_number(value: object) -> int | None:
    try:
        return int(float(str(value)))
    except (TypeError, ValueError):
        return None


def _as_money(value: object) -> float | None:
    if value is None or value == "":
        return None
    try:
        return float(str(value))
    except (TypeError, ValueError):
        return None


def parse_smiles_response(
    text: str,
    *,
    origin: str,
    destination: str,
    requested_date: date,
    window_start: date,
    window_end: date,
    booking_url: str,
) -> tuple[list[Opportunity], list[date]]:
    """Converte a resposta do Smiles em oportunidades e datas cobertas.

    O calendário não traz cabine nem taxas: é o menor valor do dia e é
    tratado como econômica. O dia central vem detalhado (cabines, taxas e
    voos) e sobrescreve o calendário para a econômica, além de trazer a
    executiva.
    """
    try:
        payload = json.loads(text)
    except json.JSONDecodeError as exc:
        raise ProviderError("Smiles devolveu uma resposta que não é JSON") from exc

    segments = payload.get("requestedFlightSegmentList") or []
    if not segments:
        return [], [requested_date]
    segment = segments[0]

    opportunities: dict[tuple[date, str], Opportunity] = {}
    covered: set[date] = {requested_date}

    for day in segment.get("calendarDayList") or []:
        day_date = _parse_date(day.get("date"))
        miles = _as_number(day.get("miles"))
        if day_date is None or miles is None or miles <= 0:
            continue
        if not (window_start <= day_date <= window_end):
            continue
        covered.add(day_date)
        opportunities[(day_date, "Y")] = Opportunity(
            provider="smiles",
            origin=origin,
            destination=destination,
            depart_date=day_date,
            cabin="Y",
            miles=miles,
            taxes_brl=None,
            flights=[],
            stops=None,
            booking_url=booking_url,
        )

    for raw in segment.get("flightList") or []:
        cabin = CABIN_BY_CODE.get(str(raw.get("cabin") or "").upper())
        if cabin is None:
            continue
        fares = raw.get("fareList") or []
        chosen = None
        for fare_type in FARE_ORDER:
            for fare in fares:
                if fare.get("type") == fare_type:
                    chosen = fare
                    break
            if chosen is not None:
                break
        if chosen is None:
            continue
        miles = _as_number(chosen.get("miles"))
        if miles is None or miles <= 0:
            continue
        departure_raw = (raw.get("departure") or {}).get("date")
        day_date = _parse_date(departure_raw) or requested_date
        if not (window_start <= day_date <= window_end):
            day_date = requested_date
        if not (window_start <= day_date <= window_end):
            continue
        covered.add(day_date)
        g3 = chosen.get("g3") or {}
        taxes = _as_money(g3.get("costTax"))
        airline_code = str((raw.get("airline") or {}).get("code") or "")
        flights: list[str] = []
        for leg in raw.get("legList") or []:
            number = leg.get("flightNumber")
            if not number:
                continue
            code = str(
                (leg.get("marketingAirline") or {}).get("code")
                or airline_code
            )
            flights.append(f"{code} {number}".strip())
        candidate = Opportunity(
            provider="smiles",
            origin=origin,
            destination=destination,
            depart_date=day_date,
            cabin=cabin,  # type: ignore[arg-type]
            miles=miles,
            taxes_brl=taxes,
            flights=flights,
            stops=_as_number(raw.get("stops")),
            booking_url=booking_url,
        )
        key = (day_date, cabin)
        current = opportunities.get(key)
        if current is None or miles < current.miles:
            opportunities[key] = candidate

    return list(opportunities.values()), sorted(covered)


def filter_for_cabin(
    opportunities: list[Opportunity],
    covered: list[date],
    cabin: Cabin,
    middle: date,
) -> tuple[list[Opportunity], list[date]]:
    if cabin == "J":
        # O calendário é o menor valor, sem cabine; para executiva só o dia
        # central foi detalhado. As demais datas não foram verificadas nessa
        # cabine e não entram em checked_dates.
        return (
            [item for item in opportunities if item.cabin == "J"],
            [middle],
        )
    return [item for item in opportunities if item.cabin == "Y"], covered


class SmilesProvider(BaseProvider):
    """Adaptador do Smiles (Gol) via API interna, em modo convidado.

    A API exige que o fetch saia de uma página no próprio domínio da API,
    por isso usamos Playwright: abrimos a raiz da API (que responde 406 como
    documento, o que é esperado) e chamamos o endpoint de busca dentro dela.
    """

    def __init__(self, code: str, config, app) -> None:
        super().__init__(code, config, app)
        self.api_key = os.environ.get("SMILES_API_KEY", DEFAULT_API_KEY)
        self._playwright = None
        self._browser = None
        self._page = None
        self._cache: dict[
            tuple[str, date, date],
            tuple[list[Opportunity], list[date], date],
        ] = {}
        self._warned_no_calendar = False

    def _ensure_page(self) -> None:
        if self._page is not None:
            return
        try:
            from playwright.sync_api import sync_playwright
        except ImportError as exc:
            raise ProviderNotImplemented(
                "Smiles: Playwright não instalado. Rode "
                "`pip install -e .[browser]` e `playwright install chromium`."
            ) from exc
        self._playwright = sync_playwright().start()
        try:
            self._browser = self._playwright.chromium.launch(headless=True)
            context = self._browser.new_context(
                locale="pt-BR", timezone_id="America/Fortaleza"
            )
            context.set_default_timeout(70_000)
            page = context.new_page()
            try:
                page.goto(
                    "https://www.smiles.com.br/",
                    wait_until="domcontentloaded",
                    timeout=60_000,
                )
                page.wait_for_timeout(3000)
            except Exception as exc:
                logger.warning("Smiles: falha ao abrir o site: %s", exc)
            try:
                response = page.goto(
                    f"{API_HOST}/",
                    wait_until="domcontentloaded",
                    timeout=60_000,
                )
                # A raiz costuma responder 403/406 como documento; o que
                # importa é a página estar na origem da API para o fetch.
                if response is not None and response.status not in (
                    200,
                    403,
                    406,
                ):
                    logger.warning(
                        "Smiles: raiz da API respondeu %s", response.status
                    )
            except Exception as exc:
                logger.warning(
                    "Smiles: falha ao abrir a raiz da API: %s", exc
                )
            page.wait_for_timeout(3000)
            self._page = page
        except Exception:
            self.close()
            raise

    def close(self) -> None:
        try:
            if self._browser is not None:
                self._browser.close()
        except Exception:
            pass
        finally:
            self._browser = None
            self._page = None
            try:
                if self._playwright is not None:
                    self._playwright.stop()
            except Exception:
                pass
            self._playwright = None

    def _search_url(
        self, origin: str, destination: str, depart: date, adults: int
    ) -> str:
        query = urlencode(
            {
                "originAirportCode": origin.upper(),
                "destinationAirportCode": destination.upper(),
                "departureDate": depart.isoformat(),
                "adults": str(adults),
                "children": "0",
                "infants": "0",
                "forceCongener": "false",
            }
        )
        return f"{API_HOST}/v1/airlines/search?{query}"

    def _call_api(
        self,
        origin: str,
        destination: str,
        depart: date,
        ctx: ScanContext,
    ) -> str:
        self._ensure_page()
        assert self._page is not None
        self.sleep_between_requests()
        self.requests += 1
        script = """
        async ({url, headers, timeoutMs}) => {
          const response = await fetch(url, {
            headers,
            signal: AbortSignal.timeout(timeoutMs),
          });
          return {status: response.status, text: await response.text()};
        }
        """
        try:
            result = self._page.evaluate(
                script,
                {
                    "url": self._search_url(
                        origin, destination, depart, ctx.adults
                    ),
                    "headers": {
                        "x-api-key": self.api_key,
                        "channel": "WEB",
                        "accept": "application/json, text/plain, */*",
                        "accept-language": "pt-BR,pt;q=0.9",
                    },
                    "timeoutMs": int(ctx.timeout_seconds * 1000),
                },
            )
        except Exception as exc:
            raise ProviderError(
                f"Smiles: falha ao executar a busca: {exc}"
            ) from exc
        status = int(result.get("status") or 0)
        text = str(result.get("text") or "")
        if status == 406:
            raise ProviderBlocked(
                "Smiles bloqueou o IP (406). Pare e aguarde; insistir piora."
            )
        if status == 403:
            raise ProviderBlocked(
                "Smiles negou o acesso na borda (403). Pare e aguarde."
            )
        if status == 452:
            raise ProviderError(
                f"Smiles respondeu 452 (janela/formato): {text[:200]}"
            )
        if status != 200:
            raise ProviderError(f"Smiles HTTP {status}: {text[:200]}")
        return text

    def scan(
        self,
        destination: str,
        cabin: Cabin,
        window_start: date,
        window_end: date,
        ctx: ScanContext,
    ) -> ScanOutcome:
        middle = window_start + timedelta(
            days=(window_end - window_start).days // 2
        )
        cache_key = (destination, window_start, window_end)
        cached = self._cache.get(cache_key)
        if cached is None:
            text = self._call_api(
                ctx.origin, destination, middle, ctx
            )
            all_opportunities, covered = parse_smiles_response(
                text,
                origin=ctx.origin,
                destination=destination,
                requested_date=middle,
                window_start=window_start,
                window_end=window_end,
                booking_url=self.config.deep_link,
            )
            self._cache[cache_key] = (
                all_opportunities,
                covered,
                middle,
            )
            if not any(
                item != middle for item in covered
            ) and not self._warned_no_calendar:
                self._warned_no_calendar = True
                logger.warning(
                    "Smiles: calendário ausente em %s → %s; "
                    "cobertura reduzida ao dia central.",
                    ctx.origin,
                    destination,
                )
        else:
            all_opportunities, covered, middle = cached

        for item in all_opportunities:
            item.booking_url = build_booking_url(
                "smiles",
                ctx.origin,
                destination,
                item.depart_date,
                item.cabin,
                ctx.adults,
                self.config.deep_link,
            )

        opportunities, task_covered = filter_for_cabin(
            all_opportunities, covered, cabin, middle
        )
        return ScanOutcome(
            provider=self.code,
            origin=ctx.origin,
            destination=destination,
            cabin=cabin,
            window_start=window_start,
            window_end=window_end,
            opportunities=opportunities,
            complete=True,
            covered_dates=task_covered,
        )
