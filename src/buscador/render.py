from __future__ import annotations

import json
import shutil
from datetime import UTC, date, datetime, timedelta
from pathlib import Path
from typing import Any

from jinja2 import Environment, FileSystemLoader, select_autoescape

from .config import AppConfig
from .deeplinks import (
    format_date_br,
    roundtrip_urls,
    roundtrip_verified,
    search_copy_text,
)
from .models import CABIN_LABELS, Opportunity
from .state import State, parse_dt

WEEKDAYS = (
    "segunda",
    "terça",
    "quarta",
    "quinta",
    "sexta",
    "sábado",
    "domingo",
)

STATUS_LABELS = {
    "ok": "OK",
    "partial": "Parcial",
    "blocked": "Bloqueado",
    "error": "Erro",
    "not_implemented": "Em implementação",
    "disabled": "Desativado",
    "pending": "Aguardando",
}

STATUS_CLASSES = {
    "ok": "ok",
    "partial": "warn",
    "blocked": "error",
    "error": "error",
    "not_implemented": "warn",
    "disabled": "muted",
    "pending": "warn",
}


def _format_miles(value: int) -> str:
    return f"{int(value):,}".replace(",", ".")


def _format_brl(value: float | None) -> str:
    if value is None:
        return ""
    text = f"{value:,.2f}"
    text = text.replace(",", "X").replace(".", ",").replace("X", ".")
    return f"R$ {text}"


def _ago(value: datetime | None, now: datetime) -> str:
    if value is None:
        return "nunca"
    seconds = max(0, int((now - value).total_seconds()))
    if seconds < 60:
        return "agora"
    minutes = seconds // 60
    if minutes < 60:
        return f"há {minutes} min"
    hours = minutes // 60
    if hours < 48:
        return f"há {hours}h"
    return f"há {hours // 24} dias"


def _next_run(now: datetime) -> datetime:
    now_utc = now.astimezone(UTC)
    base = now_utc.replace(hour=0, minute=0, second=0, microsecond=0)
    next_hour = ((now_utc.hour // 6) + 1) * 6
    next_utc = base + timedelta(hours=next_hour)
    return next_utc.astimezone(now.tzinfo)


def _weekday(value: date) -> str:
    return WEEKDAYS[value.weekday()]


def _stops_label(stops: int | None) -> str:
    if stops is None:
        return "paradas não informadas"
    if stops == 0:
        return "direto"
    if stops == 1:
        return "1 parada"
    return f"{stops} paradas"


def _card(record: dict[str, Any], cfg: AppConfig, now: datetime) -> dict[str, Any] | None:
    try:
        opportunity = Opportunity.from_dict(record)
    except (KeyError, TypeError, ValueError):
        return None
    if opportunity.miles <= 0:
        return None
    last_seen = parse_dt(record.get("last_seen"))
    if last_seen is None:
        return None
    if now - last_seen > timedelta(hours=cfg.coverage.max_age_hours):
        return None

    first_seen = parse_dt(record.get("first_seen"))
    last_alert_at = parse_dt(record.get("last_alert_at"))
    is_new = bool(
        first_seen is not None and now - first_seen <= timedelta(hours=24)
    )
    is_drop = bool(
        record.get("last_alert_kind") == "drop"
        and last_alert_at is not None
        and now - last_alert_at <= timedelta(hours=24)
    )
    below_average = bool(record.get("below_average"))
    suspicious = bool(record.get("suspicious"))
    badges: list[str] = []
    if is_new:
        badges.append("new")
    if is_drop:
        badges.append("drop")
    if below_average:
        badges.append("avg")
    if suspicious:
        badges.append("suspicious")

    provider_cfg = cfg.providers.get(opportunity.provider)
    deep_link = provider_cfg.deep_link if provider_cfg else ""
    program = cfg.program_label(opportunity.provider)
    cabin_label = CABIN_LABELS.get(opportunity.cabin, opportunity.cabin)
    rt_links = [
        {"days": days, "url": url}
        for days, url in roundtrip_urls(
            opportunity.provider,
            opportunity.origin,
            opportunity.destination,
            opportunity.depart_date,
            opportunity.cabin,
            cfg.adults,
            deep_link,
        ).items()
    ]
    booking_url = opportunity.booking_url or deep_link
    return {
        "provider": opportunity.provider,
        "program": program,
        "origin": opportunity.origin,
        "destination": opportunity.destination,
        "city": cfg.destination_city(opportunity.destination),
        "country": cfg.destination_country(opportunity.destination),
        "date_iso": opportunity.depart_date.isoformat(),
        "date_br": format_date_br(opportunity.depart_date),
        "weekday": _weekday(opportunity.depart_date),
        "cabin": opportunity.cabin,
        "cabin_label": cabin_label,
        "miles": int(opportunity.miles),
        "miles_fmt": _format_miles(int(opportunity.miles)),
        "taxes_brl": opportunity.taxes_brl,
        "taxes_fmt": _format_brl(opportunity.taxes_brl),
        "stops": opportunity.stops,
        "stops_label": _stops_label(opportunity.stops),
        "booking_url": booking_url,
        "verified_ago": _ago(
            parse_dt(record.get("last_checked_at")) or last_seen, now
        ),
        "badges": badges,
        "is_new": is_new,
        "is_drop": is_drop,
        "below_average": below_average,
        "suspicious": suspicious,
        "rt_links": rt_links,
        "rt_verified": roundtrip_verified(opportunity.provider),
        "copy_text": search_copy_text(opportunity, program),
        "first_seen_iso": first_seen.isoformat() if first_seen else "",
    }


def _provider_cards(cfg: AppConfig, state: State, now: datetime) -> list[dict[str, Any]]:
    providers: list[dict[str, Any]] = []
    for code, provider in cfg.providers.items():
        if not provider.enabled:
            continue
        data = state.raw["providers"].get(code, {})
        status = str(data.get("status") or "pending")
        last_success = parse_dt(data.get("last_success"))
        requests = data.get("requests") or 0
        navigations = data.get("navigations") or 0
        scans = data.get("scans") or 0
        error = str(data.get("error") or "").strip()
        details = [f"última coleta: {_ago(last_success, now)}"]
        if requests:
            details.append(f"{requests} requisições")
        if navigations:
            details.append(f"{navigations} navegações")
        if scans:
            details.append(f"{scans} janelas")
        if error:
            details.append(error[:120])
        providers.append(
            {
                "code": code,
                "name": provider.name,
                "status": status,
                "status_label": STATUS_LABELS.get(status, status),
                "status_class": STATUS_CLASSES.get(status, "muted"),
                "detail": " · ".join(details),
            }
        )
    return providers


def _banner(
    cfg: AppConfig, state: State, provider_cards: list[dict[str, Any]], now: datetime
) -> tuple[str, str]:
    updated = parse_dt(state.raw.get("updated_at"))
    statuses = {item["status"] for item in provider_cards}
    if updated is None:
        return "warn", "Aguardando a primeira coleta."
    if statuses and statuses.issubset(
        {"blocked", "error", "not_implemented", "disabled"}
    ):
        return "error", "Coleta indisponível ou em implementação. Veja o status abaixo."
    if statuses & {"blocked", "error", "partial"}:
        return "warn", "Coleta parcial: alguns programas podem estar desatualizados."
    if now - updated > timedelta(hours=cfg.coverage.stale_after_hours):
        return "warn", "Os dados podem estar desatualizados."
    return "ok", "Dados atualizados."


def render_site(cfg: AppConfig, state: State, now: datetime) -> Path:
    if now.tzinfo is None:
        now = now.replace(tzinfo=cfg.tz)
    records = state.raw.get("opportunities", {}).values()
    cards = [
        card
        for record in records
        if isinstance(record, dict) and record.get("available", True)
        for card in [_card(record, cfg, now)]
        if card is not None
    ]
    cards.sort(
        key=lambda card: (
            not card["is_new"],
            not card["is_drop"],
            card["miles"],
            card["date_iso"],
        )
    )
    cards = cards[: cfg.site.max_cards]

    provider_cards = _provider_cards(cfg, state, now)
    status_class, status_message = _banner(cfg, state, provider_cards, now)
    updated = parse_dt(state.raw.get("updated_at"))

    destinations = sorted(
        {
            (card["destination"], f"{card['city']} ({card['destination']})")
            for card in cards
        },
        key=lambda item: item[1],
    )
    programs = sorted(
        {(card["provider"], card["program"]) for card in cards},
        key=lambda item: item[1],
    )
    cabins = sorted(
        {(card["cabin"], card["cabin_label"]) for card in cards},
        key=lambda item: item[1],
    )
    links = [
        {"name": link.name, "url": link.url, "note": link.note}
        for link in cfg.enabled_links()
    ]

    env = Environment(
        loader=FileSystemLoader(str(cfg.templates_dir)),
        autoescape=select_autoescape(["html", "xml"]),
    )
    env.filters["miles"] = _format_miles
    env.filters["brl"] = _format_brl
    template = env.get_template("index.html.j2")
    html = template.render(
        site_title=cfg.site.title,
        origin=cfg.origin,
        updated_at=(
            updated.strftime("%d/%m/%Y %H:%M") if updated else "aguardando"
        ),
        next_run_at=_next_run(now).strftime("%d/%m/%Y %H:%M"),
        status_class=status_class,
        status_message=status_message,
        cards=cards,
        total_cards=len(cards),
        filter_destinations=destinations,
        filter_programs=programs,
        filter_cabins=cabins,
        providers=provider_cards,
        links=links,
        coverage_note=(
            "A página é regerada a cada 6h; cada rota avança em rodízio. "
            "Smiles completa o ciclo em ~1-2 dias e Azul em ~1 semana."
        ),
        generated_at=now.strftime("%d/%m/%Y %H:%M"),
    )

    cfg.site_dir.mkdir(parents=True, exist_ok=True)
    output = cfg.site_dir / "index.html"
    output.write_text(html, encoding="utf-8")
    for asset in ("style.css", "app.js"):
        source = cfg.static_dir / asset
        if source.exists():
            shutil.copy2(source, cfg.site_dir / asset)
    data = {
        "generated_at": now.isoformat(timespec="seconds"),
        "origin": cfg.origin,
        "updated_at": state.raw.get("updated_at"),
        "cards": cards,
        "providers": provider_cards,
        "links": links,
    }
    (cfg.site_dir / "data.json").write_text(
        json.dumps(data, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    return output
