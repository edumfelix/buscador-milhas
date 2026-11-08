from __future__ import annotations

import argparse
import json
import logging
import os
import sys
from datetime import datetime
from pathlib import Path

from .config import AppConfig, ConfigError, load_config
from .discovery import run_discovery
from .providers import build_provider
from .render import render_site
from .runner import RunOptions, run_once
from .state import State
from .telegram import (
    TelegramError,
    get_chat_ids,
    send_alerts,
    send_test_message,
)

logger = logging.getLogger(__name__)


def _configure_output() -> None:
    for stream in (sys.stdout, sys.stderr):
        reconfigure = getattr(stream, "reconfigure", None)
        if reconfigure is None:
            continue
        try:
            reconfigure(encoding="utf-8", errors="replace")
        except (AttributeError, OSError, ValueError):
            pass


def _setup_logging(verbose: bool) -> None:
    logging.basicConfig(
        level=logging.DEBUG if verbose else logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )
    # O httpx loga a URL completa em INFO; a URL do Telegram contém o token.
    logging.getLogger("httpx").setLevel(logging.WARNING)
    logging.getLogger("httpcore").setLevel(logging.WARNING)


def _parse_providers(raw: str | None) -> list[str] | None:
    if not raw:
        return None
    items = [item.strip() for item in raw.split(",") if item.strip()]
    return items or None


def _apply_paths(
    cfg: AppConfig, args: argparse.Namespace
) -> AppConfig:
    if getattr(args, "data_dir", None):
        cfg.data_dir = Path(args.data_dir).expanduser().resolve()
    if getattr(args, "site_dir", None):
        cfg.site_dir = Path(args.site_dir).expanduser().resolve()
    return cfg


def _selected_codes(
    cfg: AppConfig, raw: str | None
) -> tuple[list[str], bool]:
    parsed = _parse_providers(raw)
    demo = "demo" in (parsed or [])
    if demo:
        codes = [
            code for code, provider in cfg.providers.items() if provider.enabled
        ]
        return codes, True
    if parsed:
        codes = [
            code
            for code in parsed
            if code in cfg.providers and cfg.providers[code].enabled
        ]
        unknown = [code for code in parsed if code not in cfg.providers]
        if unknown:
            logger.warning("Provedores desconhecidos ignorados: %s", unknown)
        return codes, False
    return [
        code for code, provider in cfg.providers.items() if provider.enabled
    ], False


def _print_config_summary(cfg: AppConfig) -> None:
    print(f"Origem: {cfg.origin}")
    print(
        f"Horizonte: {cfg.horizon_days} dias · adultos: {cfg.adults} · "
        f"timezone: {cfg.timezone}"
    )
    print(
        "Destinos nacionais: "
        + ", ".join(cfg.destinations.get("domestic", []))
    )
    print(
        "Destinos internacionais: "
        + ", ".join(cfg.destinations.get("international", []))
    )
    for code, provider in cfg.providers.items():
        state = "habilitado" if provider.enabled else "desabilitado"
        print(
            f"Provedor {code} ({provider.name}): {state} · "
            f"janela {provider.window_days}d · orçamento {provider.budget}"
        )
    for code, link in cfg.links.items():
        state = "habilitado" if link.enabled else "desabilitado"
        print(f"Link {code} ({link.name}): {state}")
    print(
        f"Dados: {cfg.data_dir} · site: {cfg.site_dir} · "
        f"templates: {cfg.templates_dir}"
    )


def cmd_config_validate(args: argparse.Namespace) -> int:
    cfg = load_config(args.config)
    _apply_paths(cfg, args)
    _print_config_summary(cfg)
    return 0


def cmd_run(args: argparse.Namespace) -> int:
    cfg = _apply_paths(load_config(args.config), args)
    codes, demo = _selected_codes(cfg, args.providers)
    if args.demo:
        demo = True
        codes = [
            code for code, provider in cfg.providers.items() if provider.enabled
        ]
    if not codes:
        print(
            "Nenhum provedor selecionado. Verifique --providers e o config.",
            file=sys.stderr,
        )
        return 2
    providers = {
        code: build_provider(code, cfg.providers[code], cfg, demo=demo)
        for code in codes
    }
    options = RunOptions(
        max_units=args.max_units,
        deadline_minutes=args.deadline_minutes,
        dry_run=args.dry_run,
        send_alerts=not args.no_alerts,
        render=not args.no_render,
        fake_block=args.fake_block,
    )
    alert_sender = None
    if not args.dry_run and not args.no_alerts:
        alert_sender = lambda alerts: send_alerts(alerts, cfg)  # noqa: E731

    result = run_once(
        cfg,
        providers,
        options=options,
        alert_sender=alert_sender,
    )
    for code, run in result.provider_runs.items():
        provider = cfg.providers.get(code)
        name = provider.name if provider else code
        print(
            f"{name}: {run.status} · {run.scans} janela(s) · "
            f"{run.results} resultado(s) · {run.requests} req · "
            f"{run.navigations} nav"
            + (f" · {run.error}" if run.error else "")
        )
    print(
        f"Alertas: {len(result.alerts)} · mensagens Telegram: "
        f"{result.messages_sent}"
    )
    if result.rendered_path:
        print(f"Site: {result.rendered_path}")
    return 0


def cmd_site(args: argparse.Namespace) -> int:
    cfg = _apply_paths(load_config(args.config), args)
    state = State.load(cfg.data_dir)
    path = render_site(cfg, state, datetime.now(cfg.tz))
    print(f"Site gerado em {path}")
    return 0


def cmd_discover(args: argparse.Namespace) -> int:
    cfg = _apply_paths(load_config(args.config), args)
    codes = _parse_providers(args.providers) or ["all"]
    payload = run_discovery(
        cfg,
        out_path=Path(args.out).expanduser().resolve(),
        provider_codes=codes,
        probe_api=args.api,
    )
    for item in payload["providers"]:
        print(
            f"{item.get('name', item.get('code'))}: {item.get('status')} "
            f"{item.get('http_status', '')} {item.get('final_url', '')}".strip()
        )
    for item in payload.get("api_probes", []):
        line = (
            f"api {item.get('name', item.get('code'))}: "
            f"{item.get('status')}"
        )
        if item.get("opportunities") is not None:
            line += f" · {item['opportunities']} oportunidade(s)"
        if item.get("error"):
            line += f" · {str(item['error'])[:160]}"
        print(line)
    for item in payload["links"]:
        print(
            f"link {item.get('name', item.get('code'))}: {item.get('status')} "
            f"{item.get('http_status', '')}".strip()
        )
    print(f"Relatório: {Path(args.out).resolve()}")
    return 0


def cmd_telegram_chat_id(args: argparse.Namespace) -> int:
    token = args.token or os.environ.get("TELEGRAM_BOT_TOKEN", "")
    if not token:
        print(
            "Informe --token ou defina TELEGRAM_BOT_TOKEN.", file=sys.stderr
        )
        return 2
    try:
        items = get_chat_ids(token)
    except TelegramError as exc:
        print(f"Erro no Telegram: {exc}", file=sys.stderr)
        return 1
    if not items:
        print(
            "Nenhum chat encontrado. Envie /start ao bot e tente novamente."
        )
        return 0
    print(json.dumps(items, ensure_ascii=False, indent=2))
    return 0


def cmd_alerts_test(args: argparse.Namespace) -> int:
    token = args.token or os.environ.get("TELEGRAM_BOT_TOKEN", "")
    chat_id = args.chat_id or os.environ.get("TELEGRAM_CHAT_ID", "")
    if not token or not chat_id:
        print(
            "Informe --token/--chat-id ou defina TELEGRAM_BOT_TOKEN/"
            "TELEGRAM_CHAT_ID.",
            file=sys.stderr,
        )
        return 2
    try:
        send_test_message(token, chat_id)
    except TelegramError as exc:
        print(f"Erro no Telegram: {exc}", file=sys.stderr)
        return 1
    print("Mensagem de teste enviada.")
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="buscador",
        description="Buscador pessoal de passagens com milhas saindo de FOR.",
    )
    parser.add_argument(
        "--config", default="config.yaml", help="Arquivo de configuração"
    )
    parser.add_argument("--verbose", action="store_true", help="Log detalhado")
    subparsers = parser.add_subparsers(dest="command", required=True)

    config_parser = subparsers.add_parser(
        "config", help="Validar a configuração"
    )
    config_sub = config_parser.add_subparsers(
        dest="config_command", required=True
    )
    validate = config_sub.add_parser("validate", help="Validar config.yaml")
    validate.add_argument("--data-dir", default=None)
    validate.add_argument("--site-dir", default=None)
    validate.set_defaults(func=cmd_config_validate)

    run = subparsers.add_parser("run", help="Coletar, atualizar estado e gerar site")
    run.add_argument(
        "--providers",
        default="smiles,azul",
        help="Códigos separados por vírgula; use 'demo' para dados fake",
    )
    run.add_argument(
        "--demo",
        action="store_true",
        help="Usa dados determinísticos, sem rede",
    )
    run.add_argument("--max-units", type=int, default=None)
    run.add_argument("--deadline-minutes", type=float, default=35.0)
    run.add_argument("--dry-run", action="store_true")
    run.add_argument("--no-alerts", action="store_true")
    run.add_argument("--no-render", action="store_true")
    run.add_argument("--fake-block", default=None)
    run.add_argument("--data-dir", default=None)
    run.add_argument("--site-dir", default=None)
    run.set_defaults(func=cmd_run)

    site = subparsers.add_parser("site", help="Gerar o site a partir do estado")
    site.add_argument("--data-dir", default=None)
    site.add_argument("--site-dir", default=None)
    site.set_defaults(func=cmd_site)

    discover = subparsers.add_parser(
        "discover", help="Probe de conectividade e relatório de recon"
    )
    discover.add_argument("--providers", default="all")
    discover.add_argument("--out", default="artifacts/discovery.json")
    discover.add_argument(
        "--api",
        dest="api",
        action="store_true",
        default=True,
        help="Tenta uma busca real por provedor (gate G0)",
    )
    discover.add_argument(
        "--no-api",
        dest="api",
        action="store_false",
        help="Somente conectividade HTTP das páginas",
    )
    discover.add_argument("--data-dir", default=None)
    discover.add_argument("--site-dir", default=None)
    discover.set_defaults(func=cmd_discover)

    telegram = subparsers.add_parser(
        "telegram-chat-id", help="Descobrir o chat_id do Telegram"
    )
    telegram.add_argument("--token", default=None)
    telegram.set_defaults(func=cmd_telegram_chat_id)

    alerts = subparsers.add_parser("alerts", help="Testar alertas")
    alerts_sub = alerts.add_subparsers(dest="alerts_command", required=True)
    test = alerts_sub.add_parser("test", help="Enviar mensagem de teste")
    test.add_argument("--token", default=None)
    test.add_argument("--chat-id", default=None)
    test.set_defaults(func=cmd_alerts_test)

    return parser


def main(argv: list[str] | None = None) -> int:
    _configure_output()
    parser = build_parser()
    args = parser.parse_args(argv)
    _setup_logging(args.verbose)
    try:
        return int(args.func(args))
    except ConfigError as exc:
        print(f"Configuração inválida: {exc}", file=sys.stderr)
        return 2
    except KeyboardInterrupt:
        return 130
    except Exception as exc:  # pragma: no cover - proteção da CLI
        logger.exception("Falha inesperada")
        print(f"Falha inesperada: {exc}", file=sys.stderr)
        return 1
