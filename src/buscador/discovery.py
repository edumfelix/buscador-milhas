from __future__ import annotations

import json
import logging
import time
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any

import httpx

from .config import AppConfig
from .providers import build_provider
from .providers.base import (
    ProviderBlocked,
    ProviderError,
    ProviderNotImplemented,
    ScanContext,
)

logger = logging.getLogger(__name__)

USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/124.0 Safari/537.36"
)

RECON_NOTES = [
    "LATAM Pass: busca award anônima redireciona para login (Auth0 + MFA); v2.",
    "Smiles: 406 JSON é quota por IP; calendário de ~7 dias com channel=WEB.",
    "Azul: exige Playwright/interceptação; 6 datas por chamada; "
    "~8 navegações seguidas podem bloquear o IP.",
    "Sem credenciais de companhias: somente buscas de convidado.",
]


def probe_url(url: str, *, timeout: float = 20.0) -> dict[str, Any]:
    if not url:
        return {"url": "", "status": "skipped", "error": "URL vazia"}
    started = time.monotonic()
    try:
        with httpx.Client(
            follow_redirects=True,
            timeout=timeout,
            headers={
                "User-Agent": USER_AGENT,
                "Accept-Language": "pt-BR,pt;q=0.9,en;q=0.8",
                "Accept": "text/html,application/xhtml+xml",
            },
        ) as client:
            response = client.get(url)
    except httpx.HTTPError as exc:
        return {
            "url": url,
            "status": "error",
            "error": str(exc)[:200],
            "elapsed_ms": int((time.monotonic() - started) * 1000),
        }
    elapsed = int((time.monotonic() - started) * 1000)
    if 200 <= response.status_code < 400:
        status = "ok"
    elif response.status_code in (403, 406, 429):
        status = "blocked"
    else:
        status = "error"
    return {
        "url": url,
        "final_url": str(response.url),
        "http_status": response.status_code,
        "status": status,
        "elapsed_ms": elapsed,
    }


def probe_provider_api(cfg: AppConfig, code: str) -> dict[str, Any]:
    provider_config = cfg.providers.get(code)
    if provider_config is None or not provider_config.enabled:
        return {
            "code": code,
            "status": "skipped",
            "error": "provedor desabilitado",
        }
    provider = build_provider(code, provider_config, cfg)
    now = datetime.now(cfg.tz)
    start = now.date() + timedelta(days=7)
    end = start + timedelta(
        days=max(1, provider_config.window_days) - 1
    )
    context = ScanContext(
        origin=cfg.origin,
        adults=cfg.adults,
        now=now,
        timeout_seconds=provider_config.timeout_seconds,
    )
    result: dict[str, Any] = {
        "code": code,
        "name": provider_config.name,
    }
    try:
        outcome = provider.scan("GRU", "Y", start, end, context)
    except ProviderBlocked as exc:
        result.update(status="blocked", error=str(exc))
    except ProviderNotImplemented as exc:
        result.update(status="not_implemented", error=str(exc))
    except ProviderError as exc:
        result.update(status="error", error=str(exc))
    except Exception as exc:  # pragma: no cover - proteção do probe
        result.update(status="error", error=str(exc)[:200])
    else:
        result.update(
            status="ok",
            opportunities=len(outcome.opportunities),
            covered_dates=[
                item.isoformat() for item in (outcome.covered_dates or [])
            ],
            complete=outcome.complete,
        )
    finally:
        result["requests"] = provider.requests
        result["navigations"] = provider.navigations
        try:
            provider.close()
        except Exception:  # pragma: no cover - proteção do probe
            logger.exception("Falha ao fechar o provedor no probe: %s", code)
    return result


def run_discovery(
    cfg: AppConfig,
    *,
    out_path: Path,
    provider_codes: list[str] | None = None,
    probe_api: bool = True,
) -> dict[str, Any]:
    selected = (
        set(provider_codes)
        if provider_codes and "all" not in provider_codes
        else {code for code, provider in cfg.providers.items() if provider.enabled}
    )
    providers: list[dict[str, Any]] = []
    for code, provider in cfg.providers.items():
        if code not in selected:
            continue
        logger.info("Probe de conectividade: %s", code)
        result = probe_url(provider.deep_link, timeout=provider.timeout_seconds)
        result["code"] = code
        result["name"] = provider.name
        providers.append(result)

    links: list[dict[str, Any]] = []
    for link in cfg.enabled_links():
        logger.info("Probe de link: %s", link.code)
        result = probe_url(link.url)
        result["code"] = link.code
        result["name"] = link.name
        links.append(result)

    api_probes: list[dict[str, Any]] = []
    if probe_api:
        for code in cfg.providers:
            if code not in selected:
                continue
            logger.info("Probe de API: %s", code)
            api_probes.append(probe_provider_api(cfg, code))

    payload = {
        "generated_at": datetime.now(cfg.tz).isoformat(timespec="seconds"),
        "origin": cfg.origin,
        "providers": providers,
        "api_probes": api_probes,
        "links": links,
        "recon_notes": RECON_NOTES,
        "next_step": (
            "O probe HTTP valida a conectividade das páginas; o probe de API "
            "tenta uma janela real (G0). Se o status for blocked, não insista: "
            "reduza o escopo ou mova a coleta para outro IP. O spike completo "
            "deve gerar fixtures sanitizadas em docs/recon/."
        ),
    }
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    return payload
