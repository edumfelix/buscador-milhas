from __future__ import annotations

import logging
import time
from collections import defaultdict
from collections.abc import Callable
from dataclasses import dataclass
from datetime import date, datetime, timedelta

from .config import AppConfig, Task
from .models import (
    Alert,
    ProviderRun,
    RunResult,
    coverage_key,
)
from .providers.base import (
    BaseProvider,
    ProviderBlocked,
    ProviderError,
    ProviderNotImplemented,
    ScanContext,
)
from .render import render_site
from .state import State, parse_dt

logger = logging.getLogger(__name__)


@dataclass
class RunOptions:
    max_units: int | None = None
    deadline_minutes: float = 35.0
    dry_run: bool = False
    send_alerts: bool = True
    render: bool = True
    bootstrap: bool | None = None
    fake_block: str | None = None


def _task_sort_key(
    task: Task, cfg: AppConfig, state: State
) -> tuple[int, float, int, str, str]:
    cov = state.raw["coverage"].get(
        coverage_key(task.provider, cfg.origin, task.destination, task.cabin), {}
    )
    last = parse_dt(cov.get("last_checked_at"))
    last_ts = last.timestamp() if last is not None else 0.0
    status = cov.get("status")
    retry_priority = 0 if status in ("error", "partial") else 1
    hot = task.destination in cfg.coverage.hot_destinations
    hot_boost = 7200 if hot else 0
    return (
        retry_priority,
        last_ts - hot_boost,
        0 if hot else 1,
        task.destination,
        task.cabin,
    )


def _provider_horizon(
    cfg: AppConfig, provider_config, today: date
) -> date:
    days = min(cfg.horizon_days, provider_config.sale_window_days)
    return today + timedelta(days=days)


def _run_provider(
    cfg: AppConfig,
    provider: BaseProvider,
    provider_config,
    tasks: list[Task],
    state: State,
    now: datetime,
    options: RunOptions,
    bootstrap: bool,
) -> tuple[ProviderRun, list[Alert]]:
    run = ProviderRun(
        provider=provider.code,
        status="ok",
        started_at=now,
    )
    alerts: list[Alert] = []
    if not tasks:
        run.status = "disabled"
        run.finished_at = now
        return run, alerts

    if options.fake_block == provider.code:
        run.status = "blocked"
        run.error = "bloqueio simulado"
        run.finished_at = now
        return run, alerts

    today = now.date()
    horizon_end = _provider_horizon(cfg, provider_config, today)
    budget = provider_config.budget
    if options.max_units is not None:
        budget = min(budget, options.max_units)
    deadline = time.monotonic() + options.deadline_minutes * 60
    scans = 0
    errors: list[str] = []
    stop = False

    while scans < budget and time.monotonic() < deadline and not stop:
        ordered = sorted(tasks, key=lambda task: _task_sort_key(task, cfg, state))
        progressed = False
        for task in ordered:
            if scans >= budget or time.monotonic() >= deadline:
                break
            cov_key = coverage_key(
                provider.code, cfg.origin, task.destination, task.cabin
            )
            start = state.next_start(cov_key, today, horizon_end)
            if start > horizon_end:
                continue
            end = min(
                start + timedelta(days=provider_config.window_days - 1),
                horizon_end,
            )
            ctx = ScanContext(
                origin=cfg.origin,
                adults=cfg.adults,
                now=now,
                timeout_seconds=provider_config.timeout_seconds,
            )
            try:
                outcome = provider.scan(
                    task.destination, task.cabin, start, end, ctx
                )
            except ProviderBlocked as exc:
                run.status = "blocked"
                run.error = str(exc)
                state.record_task_error(cov_key, now, str(exc))
                stop = True
                break
            except ProviderNotImplemented as exc:
                run.status = "not_implemented"
                run.error = str(exc)
                stop = True
                break
            except ProviderError as exc:
                errors.append(str(exc))
                state.record_task_error(cov_key, now, str(exc))
                continue
            except Exception as exc:  # pragma: no cover - proteção defensiva
                logger.exception("Erro inesperado no provedor %s", provider.code)
                run.status = "error"
                run.error = str(exc)
                state.record_task_error(cov_key, now, str(exc))
                stop = True
                break

            scans += 1
            progressed = True
            run.scans = scans
            run.requests = provider.requests
            run.navigations = provider.navigations
            run.results += len(outcome.opportunities)
            if outcome.error:
                errors.append(outcome.error)
            alerts.extend(
                state.apply_outcome(
                    outcome,
                    now,
                    cfg,
                    bootstrap=bootstrap,
                    today=today,
                    horizon_end=horizon_end,
                )
            )
        if not progressed:
            break

    if errors and run.status == "ok":
        run.status = "partial"
        run.error = "; ".join(errors[-3:])
    if run.scans == 0 and run.status == "ok":
        run.status = "partial"
        run.error = run.error or "nenhuma janela coletada (orçamento/prazo)"
    run.finished_at = now
    run.requests = provider.requests
    run.navigations = provider.navigations
    return run, alerts


def run_once(
    cfg: AppConfig,
    providers: dict[str, BaseProvider],
    *,
    now: datetime | None = None,
    options: RunOptions | None = None,
    state: State | None = None,
    alert_sender: Callable[[list[Alert]], int] | None = None,
) -> RunResult:
    options = options or RunOptions()
    run_start = now or datetime.now(cfg.tz)
    if run_start.tzinfo is None:
        run_start = run_start.replace(tzinfo=cfg.tz)
    state = state or State.load(cfg.data_dir)
    bootstrap = (
        options.bootstrap
        if options.bootstrap is not None
        else not bool(state.raw.get("bootstrap_done"))
    )
    state.begin_run(run_start)

    tasks_by_provider: dict[str, list[Task]] = defaultdict(list)
    for task in cfg.tasks():
        tasks_by_provider[task.provider].append(task)

    provider_runs: dict[str, ProviderRun] = {}
    alerts: list[Alert] = []
    for code, provider in providers.items():
        provider_config = cfg.providers.get(code)
        if provider_config is None or not provider_config.enabled:
            continue
        try:
            run, run_alerts = _run_provider(
                cfg,
                provider,
                provider_config,
                tasks_by_provider.get(code, []),
                state,
                run_start,
                options,
                bootstrap,
            )
        finally:
            try:
                provider.close()
            except Exception:  # pragma: no cover - proteção de recurso
                logger.exception("Falha ao fechar o provedor %s", code)
        state.record_provider_run(run)
        provider_runs[code] = run
        alerts.extend(run_alerts)
        logger.info(
            "Provedor %s: status=%s scans=%s resultados=%s",
            code,
            run.status,
            run.scans,
            run.results,
        )

    state.end_run(run_start)
    if not options.dry_run:
        state.save()

    rendered_path = None
    if options.render:
        rendered_path = str(render_site(cfg, state, run_start))

    messages_sent = 0
    if (
        alerts
        and options.send_alerts
        and not options.dry_run
        and alert_sender is not None
    ):
        try:
            messages_sent = alert_sender(alerts)
        except Exception:  # pragma: no cover - falha de rede/credenciais
            logger.exception("Falha ao enviar alertas ao Telegram")

    return RunResult(
        alerts=alerts,
        provider_runs=provider_runs,
        rendered_path=rendered_path,
        messages_sent=messages_sent,
    )
