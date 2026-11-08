from __future__ import annotations

import html
import logging
import os
import time
from datetime import datetime
from typing import Any

import httpx

from .config import AppConfig
from .deeplinks import format_date_br
from .models import CABIN_LABELS, Alert

logger = logging.getLogger(__name__)

TELEGRAM_LIMIT = 4096
SAFE_LIMIT = 3900


class TelegramError(RuntimeError):
    """Falha ao falar com a Bot API."""


def _format_miles(value: int) -> str:
    return f"{int(value):,}".replace(",", ".")


def _format_brl(value: float | None) -> str:
    if value is None:
        return ""
    text = f"{value:,.2f}"
    text = text.replace(",", "X").replace(".", ",").replace("X", ".")
    return f"R$ {text}"


def split_message(text: str, limit: int = SAFE_LIMIT) -> list[str]:
    if len(text) <= limit:
        return [text]
    parts: list[str] = []
    current = ""
    for line in text.splitlines(keepends=True):
        while len(line) > limit:
            if current:
                parts.append(current)
                current = ""
            parts.append(line[:limit])
            line = line[limit:]
        if len(current) + len(line) > limit:
            parts.append(current)
            current = ""
        current += line
    if current:
        parts.append(current)
    return parts


class TelegramClient:
    def __init__(
        self,
        token: str,
        chat_id: str | int,
        *,
        base_url: str = "https://api.telegram.org",
        timeout: float = 20.0,
    ) -> None:
        self._token = token
        self.chat_id = str(chat_id)
        self.base_url = base_url.rstrip("/")
        self.timeout = timeout

    def __repr__(self) -> str:
        return f"TelegramClient(chat_id={self.chat_id!r})"

    def _url(self, method: str) -> str:
        return f"{self.base_url}/bot{self._token}/{method}"

    def _request(
        self, method: str, payload: dict[str, Any], *, attempts: int = 3
    ) -> dict[str, Any]:
        last_error: Exception | None = None
        for attempt in range(attempts):
            try:
                with httpx.Client(timeout=self.timeout) as client:
                    response = client.post(self._url(method), json=payload)
            except httpx.HTTPError as exc:
                last_error = exc
                if attempt < attempts - 1:
                    time.sleep(2 * (attempt + 1))
                    continue
                raise TelegramError(f"Falha de rede no Telegram: {exc}") from exc

            if response.status_code == 429:
                try:
                    retry_after = int(
                        response.json().get("parameters", {}).get("retry_after", 5)
                    )
                except (ValueError, TypeError):
                    retry_after = 5
                if attempt < attempts - 1:
                    time.sleep(min(retry_after, 30))
                    continue
                raise TelegramError("Limite de requisições do Telegram")
            if 500 <= response.status_code < 600:
                last_error = TelegramError(
                    f"Telegram {response.status_code}"
                )
                if attempt < attempts - 1:
                    time.sleep(2 * (attempt + 1))
                    continue
                raise last_error
            if response.status_code >= 400:
                try:
                    description = response.json().get("description", "")
                except ValueError:
                    description = response.text[:200]
                raise TelegramError(
                    f"Telegram {response.status_code}: {description}"
                )
            try:
                data = response.json()
            except ValueError as exc:
                raise TelegramError("Resposta inválida do Telegram") from exc
            if not data.get("ok"):
                raise TelegramError(
                    f"Telegram recusou a mensagem: {data.get('description', '')}"
                )
            return data
        raise TelegramError(f"Falha no Telegram: {last_error}")

    def send_message(self, text: str) -> dict[str, Any]:
        return self._request(
            "sendMessage",
            {
                "chat_id": self.chat_id,
                "text": text,
                "parse_mode": "HTML",
                "disable_web_page_preview": True,
            },
        )

    def get_updates(self) -> list[dict[str, Any]]:
        try:
            with httpx.Client(timeout=self.timeout) as client:
                response = client.get(
                    self._url("getUpdates"), params={"timeout": 0}
                )
        except httpx.HTTPError as exc:
            raise TelegramError(f"Falha de rede no Telegram: {exc}") from exc
        if response.status_code >= 400:
            raise TelegramError(f"Telegram {response.status_code}")
        data = response.json()
        if not data.get("ok"):
            raise TelegramError(
                f"Telegram recusou getUpdates: {data.get('description', '')}"
            )
        return list(data.get("result") or [])


def format_alert(alert: Alert, cfg: AppConfig) -> str:
    opportunity = alert.opportunity
    route = f"{opportunity.origin} → {opportunity.destination}"
    date = format_date_br(opportunity.depart_date)
    cabin = CABIN_LABELS.get(opportunity.cabin, opportunity.cabin)
    program = html.escape(cfg.program_label(opportunity.provider))
    miles = _format_miles(opportunity.miles)
    taxes = _format_brl(opportunity.taxes_brl)
    taxes_text = f" + {taxes}" if taxes else ""
    provider_cfg = cfg.providers.get(opportunity.provider)
    url = opportunity.booking_url or (
        provider_cfg.deep_link if provider_cfg else ""
    )
    link = (
        f'\n<a href="{html.escape(url, quote=True)}">Abrir no programa</a>'
        if url
        else ""
    )
    if alert.kind == "new":
        return (
            f"<b>{html.escape(route)}</b> · {date} · {program} · {cabin}\n"
            f"{miles} milhas{taxes_text}{link}"
        )
    previous = _format_miles(alert.previous_miles or 0)
    pct = f"-{alert.drop_pct:.1f}%" if alert.drop_pct is not None else ""
    return (
        f"<b>{html.escape(route)}</b> · {date} · {program} · {cabin}\n"
        f"{miles} milhas (era {previous}, {pct}){taxes_text}{link}"
    )


def build_digest(
    alerts: list[Alert], cfg: AppConfig, *, site_url: str = ""
) -> list[str]:
    if not alerts:
        return []
    max_items = (
        cfg.alerting.max_items_per_message
        * cfg.alerting.max_messages_per_run
    )
    selected = alerts[:max_items]
    hidden = len(alerts) - len(selected)
    new_alerts = [item for item in selected if item.kind == "new"]
    drop_alerts = [item for item in selected if item.kind == "drop"]
    lines = ["<b>Oportunidades com milhas — FOR</b>"]
    if new_alerts:
        lines.append("")
        lines.append("<b>Novas oportunidades</b>")
        lines.extend(format_alert(item, cfg) for item in new_alerts)
    if drop_alerts:
        lines.append("")
        lines.append("<b>Quedas de preço</b>")
        lines.extend(format_alert(item, cfg) for item in drop_alerts)
    if hidden:
        lines.append("")
        lines.append(f"… e mais {hidden} oportunidade(s).")
    lines.append("")
    lines.append(
        f"Atualizado: {datetime.now(cfg.tz).strftime('%d/%m/%Y %H:%M')}"
    )
    if site_url:
        lines.append(
            f'<a href="{html.escape(site_url, quote=True)}">Ver a página</a>'
        )
    messages = split_message("\n".join(lines))
    return messages[: cfg.alerting.max_messages_per_run]


def send_alerts(
    alerts: list[Alert],
    cfg: AppConfig,
    *,
    site_url: str | None = None,
) -> int:
    token = os.environ.get("TELEGRAM_BOT_TOKEN", "").strip()
    chat_id = os.environ.get("TELEGRAM_CHAT_ID", "").strip()
    if not token or not chat_id:
        logger.warning(
            "Telegram não configurado (TELEGRAM_BOT_TOKEN/TELEGRAM_CHAT_ID); "
            "alertas não enviados."
        )
        return 0
    if not alerts:
        return 0
    messages = build_digest(
        alerts,
        cfg,
        site_url=site_url if site_url is not None else os.environ.get("SITE_URL", ""),
    )
    client = TelegramClient(token, chat_id)
    sent = 0
    for message in messages:
        client.send_message(message)
        sent += 1
        time.sleep(0.4)
    logger.info("Telegram: %s mensagem(ns) enviada(s)", sent)
    return sent


def get_chat_ids(token: str) -> list[dict[str, str]]:
    client = TelegramClient(token, "0")
    updates = client.get_updates()
    found: dict[str, dict[str, str]] = {}
    for update in updates:
        message = update.get("message") or update.get("edited_message") or {}
        chat = message.get("chat") or {}
        chat_id = chat.get("id")
        if chat_id is None:
            continue
        name = (
            chat.get("title")
            or chat.get("username")
            or chat.get("first_name")
            or str(chat_id)
        )
        found[str(chat_id)] = {"id": str(chat_id), "name": str(name)}
    return list(found.values())


def send_test_message(token: str, chat_id: str) -> None:
    client = TelegramClient(token, chat_id)
    client.send_message(
        "<b>Buscador de Milhas</b>\n"
        "Teste de conexão concluído. Os alertas chegarão por aqui."
    )
