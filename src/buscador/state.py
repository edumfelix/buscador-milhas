from __future__ import annotations

import json
import logging
import statistics
from datetime import UTC, date, datetime, timedelta
from pathlib import Path
from typing import Any

from .config import AppConfig
from .models import (
    Alert,
    Opportunity,
    ProviderRun,
    ScanOutcome,
    coverage_key,
)

logger = logging.getLogger(__name__)

STATE_VERSION = 1
BASELINE_MAX_DAYS = 10
HISTORY_RETENTION_DAYS = 180
MEDIAN_WINDOW_DAYS = 60
MEDIAN_MIN_OBSERVATIONS = 5
RUN_HISTORY_LIMIT = 50


def now_iso(value: datetime) -> str:
    return value.isoformat(timespec="seconds")


def parse_dt(value: Any) -> datetime | None:
    if not value:
        return None
    try:
        parsed = datetime.fromisoformat(str(value))
    except (TypeError, ValueError):
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=UTC)
    return parsed


def parse_date(value: Any) -> date | None:
    if not value:
        return None
    try:
        return date.fromisoformat(str(value))
    except (TypeError, ValueError):
        return None


def _default_state() -> dict[str, Any]:
    return {
        "version": STATE_VERSION,
        "updated_at": None,
        "bootstrap_done": False,
        "opportunities": {},
        "coverage": {},
        "providers": {},
        "runs": [],
    }


def _atomic_write(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temp = path.with_name(f".{path.name}.tmp")
    temp.write_text(content, encoding="utf-8")
    temp.replace(path)


class State:
    """Estado persistido em JSON + histórico JSONL, sem banco de dados."""

    def __init__(self, state_path: Path, history_path: Path) -> None:
        self.state_path = state_path
        self.history_path = history_path
        self.raw: dict[str, Any] = _default_state()
        self.history: list[dict[str, Any]] = []
        self._checked_cache: dict[str, set[str]] | None = None
        self._medians: dict[tuple[str, str, str], float] | None = None

    @classmethod
    def load(cls, data_dir: Path) -> State:
        state = cls(data_dir / "state.json", data_dir / "history.jsonl")
        if state.state_path.exists():
            try:
                loaded = json.loads(state.state_path.read_text(encoding="utf-8"))
                if isinstance(loaded, dict):
                    state.raw = _default_state() | loaded
                else:
                    raise ValueError("estado não é um objeto JSON")
            except (OSError, ValueError, json.JSONDecodeError) as exc:
                backup = state.state_path.with_name(
                    f"state.corrupt.{datetime.now().strftime('%Y%m%d%H%M%S')}.json"
                )
                try:
                    state.state_path.replace(backup)
                except OSError:
                    pass
                logger.error("Estado inválido (%s); backup em %s", exc, backup)
                state.raw = _default_state()
        state._normalize()
        state._load_history()
        return state

    def _normalize(self) -> None:
        self.raw.setdefault("version", STATE_VERSION)
        self.raw.setdefault("updated_at", None)
        self.raw.setdefault("bootstrap_done", False)
        for key in ("opportunities", "coverage", "providers"):
            if not isinstance(self.raw.get(key), dict):
                self.raw[key] = {}
        if not isinstance(self.raw.get("runs"), list):
            self.raw["runs"] = []
        self.raw["bootstrap_done"] = bool(self.raw.get("bootstrap_done"))

    def _load_history(self) -> None:
        if not self.history_path.exists():
            return
        skipped = 0
        try:
            lines = self.history_path.read_text(encoding="utf-8").splitlines()
        except OSError as exc:
            logger.warning("Não foi possível ler o histórico: %s", exc)
            return
        for line in lines:
            if not line.strip():
                continue
            try:
                item = json.loads(line)
                if isinstance(item, dict) and item.get("miles") is not None:
                    self.history.append(item)
                else:
                    skipped += 1
            except json.JSONDecodeError:
                skipped += 1
        if skipped:
            logger.warning("%s linha(s) inválida(s) ignorada(s) no histórico", skipped)

    def begin_run(self, now: datetime) -> None:
        self._checked_cache = {
            key: set(cov.get("checked_dates") or [])
            for key, cov in self.raw["coverage"].items()
        }
        self._medians = self._compute_medians(now)

    def _ensure_caches(self, now: datetime) -> None:
        if self._checked_cache is None:
            self._checked_cache = {
                key: set(cov.get("checked_dates") or [])
                for key, cov in self.raw["coverage"].items()
            }
        if self._medians is None:
            self._medians = self._compute_medians(now)

    def _compute_medians(self, now: datetime) -> dict[tuple[str, str, str], float]:
        cutoff = now - timedelta(days=MEDIAN_WINDOW_DAYS)
        groups: dict[tuple[str, str, str], list[int]] = {}
        for item in self.history:
            observed = parse_dt(item.get("ts"))
            if observed is None or observed < cutoff:
                continue
            try:
                key = (
                    str(item["provider"]),
                    str(item["destination"]),
                    str(item["cabin"]),
                )
                groups.setdefault(key, []).append(int(item["miles"]))
            except (KeyError, TypeError, ValueError):
                continue
        return {
            key: float(statistics.median(values))
            for key, values in groups.items()
            if len(values) >= MEDIAN_MIN_OBSERVATIONS
        }

    def _median_for(self, provider: str, destination: str, cabin: str) -> float | None:
        return (self._medians or {}).get((provider, destination, cabin))

    def _was_checked(
        self, cov_key: str, depart_date: date, now: datetime
    ) -> bool:
        cov = self.raw["coverage"].get(cov_key, {})
        last_checked = parse_dt(cov.get("last_checked_at"))
        if last_checked is None or (
            now - last_checked
        ) > timedelta(days=BASELINE_MAX_DAYS):
            return False
        return depart_date.isoformat() in (
            self._checked_cache or {}
        ).get(cov_key, set())

    def _cooldown_ok(
        self, record: dict[str, Any], now: datetime, cfg: AppConfig
    ) -> bool:
        last = parse_dt(record.get("last_alert_at"))
        if last is None:
            return True
        return (now - last) >= timedelta(hours=cfg.alerting.cooldown_hours)

    def _mark_alert(
        self,
        record: dict[str, Any],
        kind: str,
        opportunity: Opportunity,
        now: datetime,
        drop_pct: float | None = None,
    ) -> None:
        record["last_alert_at"] = now_iso(now)
        record["last_alert_kind"] = kind
        record["last_alert_miles"] = opportunity.miles
        if drop_pct is not None:
            record["last_drop_pct"] = round(drop_pct, 1)

    def _opportunity_fields(
        self, opportunity: Opportunity, now: datetime
    ) -> dict[str, Any]:
        return {
            "provider": opportunity.provider,
            "origin": opportunity.origin,
            "destination": opportunity.destination,
            "depart_date": opportunity.depart_date.isoformat(),
            "cabin": opportunity.cabin,
            "miles": int(opportunity.miles),
            "taxes_brl": opportunity.taxes_brl,
            "flights": list(opportunity.flights),
            "stops": opportunity.stops,
            "booking_url": opportunity.booking_url,
            "last_seen": now_iso(now),
            "last_checked_at": now_iso(now),
        }

    def _new_record(self, opportunity: Opportunity, now: datetime) -> dict[str, Any]:
        record = self._opportunity_fields(opportunity, now)
        record.update(
            {
                "first_seen": now_iso(now),
                "available": True,
                "lowest_miles": int(opportunity.miles),
                "below_average": False,
                "suspicious": False,
            }
        )
        return record

    def _update_record(
        self, record: dict[str, Any], opportunity: Opportunity, now: datetime
    ) -> None:
        record.update(self._opportunity_fields(opportunity, now))
        record["available"] = True

    def _append_history(self, opportunity: Opportunity, now: datetime) -> None:
        self.history.append(
            {
                "ts": now_iso(now),
                "provider": opportunity.provider,
                "origin": opportunity.origin,
                "destination": opportunity.destination,
                "cabin": opportunity.cabin,
                "depart_date": opportunity.depart_date.isoformat(),
                "miles": int(opportunity.miles),
                "taxes_brl": opportunity.taxes_brl,
            }
        )

    def apply_outcome(
        self,
        outcome: ScanOutcome,
        now: datetime,
        cfg: AppConfig,
        *,
        bootstrap: bool,
        today: date,
        horizon_end: date,
    ) -> list[Alert]:
        self._ensure_caches(now)
        alerts: list[Alert] = []
        cov_key = outcome.coverage_key
        found: set[str] = set()

        if outcome.covered_dates is None:
            covered_dates = []
            current_date = outcome.window_start
            while current_date <= outcome.window_end:
                covered_dates.append(current_date)
                current_date += timedelta(days=1)
        else:
            covered_dates = list(outcome.covered_dates)
        covered_set = {
            item
            for item in covered_dates
            if outcome.window_start <= item <= outcome.window_end
        }

        best: dict[str, Opportunity] = {}
        for opportunity in outcome.opportunities:
            if opportunity.miles <= 0:
                continue
            if opportunity.depart_date not in covered_set:
                continue
            current = best.get(opportunity.key)
            if current is None or opportunity.miles < current.miles:
                best[opportunity.key] = opportunity

        for key, opportunity in best.items():
            found.add(key)
            existing = self.raw["opportunities"].get(key)
            was_checked = self._was_checked(
                cov_key, opportunity.depart_date, now
            )
            prev_miles = opportunity.miles
            was_available = True

            if existing is None:
                record = self._new_record(opportunity, now)
                self.raw["opportunities"][key] = record
                if (
                    not bootstrap
                    and was_checked
                    and cfg.alerting.new_enabled
                    and self._cooldown_ok(record, now, cfg)
                ):
                    alerts.append(Alert("new", opportunity))
                    self._mark_alert(record, "new", opportunity, now)
            else:
                prev_miles = int(existing.get("miles") or opportunity.miles)
                was_available = bool(existing.get("available", True))
                prev_seen = parse_dt(existing.get("last_seen"))

                if not was_available:
                    self._update_record(existing, opportunity, now)
                    existing["first_seen"] = now_iso(now)
                    existing["suspicious"] = False
                    if (
                        not bootstrap
                        and was_checked
                        and cfg.alerting.new_enabled
                        and self._cooldown_ok(existing, now, cfg)
                    ):
                        alerts.append(Alert("new", opportunity))
                        self._mark_alert(existing, "new", opportunity, now)
                else:
                    suspicious = False
                    if opportunity.miles < prev_miles:
                        drop_pct = (
                            (prev_miles - opportunity.miles) / prev_miles * 100
                        )
                        fresh = prev_seen is not None and (
                            now - prev_seen
                        ) <= timedelta(days=BASELINE_MAX_DAYS)
                        if drop_pct > cfg.alerting.suspicious_drop_pct:
                            suspicious = True
                        elif (
                            drop_pct >= cfg.alerting.drop_min_pct
                            and (prev_miles - opportunity.miles)
                            >= cfg.alerting.drop_min_miles
                            and fresh
                            and not bootstrap
                            and self._cooldown_ok(existing, now, cfg)
                        ):
                            alerts.append(
                                Alert(
                                    "drop",
                                    opportunity,
                                    previous_miles=prev_miles,
                                    drop_pct=round(drop_pct, 1),
                                )
                            )
                            self._mark_alert(
                                existing, "drop", opportunity, now, drop_pct
                            )
                    self._update_record(existing, opportunity, now)
                    existing["suspicious"] = suspicious

                existing["lowest_miles"] = min(
                    int(existing.get("lowest_miles") or opportunity.miles),
                    opportunity.miles,
                )

            record = self.raw["opportunities"][key]
            record.setdefault("first_seen", now_iso(now))
            median = self._median_for(
                opportunity.provider, opportunity.destination, opportunity.cabin
            )
            record["below_average"] = bool(
                median is not None and opportunity.miles <= median * 0.85
            )
            if existing is None or prev_miles != opportunity.miles or not was_available:
                self._append_history(opportunity, now)

        if outcome.complete:
            for key, record in self.raw["opportunities"].items():
                if key in found:
                    continue
                if record.get("provider") != outcome.provider:
                    continue
                if record.get("origin") != outcome.origin:
                    continue
                if record.get("destination") != outcome.destination:
                    continue
                if record.get("cabin") != outcome.cabin:
                    continue
                depart_date = parse_date(record.get("depart_date"))
                if depart_date is None:
                    continue
                if (
                    depart_date in covered_set
                    and record.get("available", True)
                ):
                    record["available"] = False
                    record["last_checked_at"] = now_iso(now)

        cov = self.raw["coverage"].setdefault(cov_key, {})
        cov["provider"] = outcome.provider
        cov["origin"] = outcome.origin
        cov["destination"] = outcome.destination
        cov["cabin"] = outcome.cabin
        cov["window_start"] = outcome.window_start.isoformat()
        cov["window_end"] = outcome.window_end.isoformat()
        cov["last_checked_at"] = now_iso(now)
        cov["status"] = "ok" if outcome.complete else "partial"
        cov["error"] = outcome.error

        if outcome.complete:
            checked = set(cov.get("checked_dates") or [])
            checked.update(item.isoformat() for item in covered_set)
            cov["checked_dates"] = sorted(checked)
            if self._checked_cache is not None:
                self._checked_cache[cov_key] = checked
            next_start = outcome.window_end + timedelta(days=1)
            if next_start > horizon_end:
                next_start = today + timedelta(days=1)
            cov["next_start"] = next_start.isoformat()
        else:
            cov.setdefault("next_start", outcome.window_start.isoformat())

        return alerts

    def record_task_error(
        self, cov_key: str, now: datetime, error: str
    ) -> None:
        cov = self.raw["coverage"].setdefault(cov_key, {})
        cov["last_checked_at"] = now_iso(now)
        cov["status"] = "error"
        cov["error"] = error

    def record_provider_run(self, run: ProviderRun) -> None:
        data = run.to_dict()
        previous = self.raw["providers"].get(run.provider, {})
        last_success = previous.get("last_success")
        if run.status in ("ok", "partial") and run.scans > 0:
            last_success = now_iso(run.finished_at or run.started_at)
        data["last_success"] = last_success
        self.raw["providers"][run.provider] = data
        runs = self.raw.setdefault("runs", [])
        runs.append(data)
        self.raw["runs"] = runs[-RUN_HISTORY_LIMIT:]

    def next_start(
        self, cov_key: str, today: date, horizon_end: date
    ) -> date:
        cov = self.raw["coverage"].get(cov_key, {})
        start = parse_date(cov.get("next_start"))
        minimum = today + timedelta(days=1)
        if start is None or start < minimum or start > horizon_end:
            return minimum
        return start

    def end_run(self, now: datetime) -> None:
        self.raw["bootstrap_done"] = True
        self.raw["updated_at"] = now_iso(now)
        self.prune(now)

    def prune(self, now: datetime) -> None:
        today = now.date()
        kept: dict[str, Any] = {}
        for key, record in self.raw["opportunities"].items():
            depart_date = parse_date(record.get("depart_date"))
            if depart_date is not None and depart_date >= today:
                kept[key] = record
        self.raw["opportunities"] = kept

        history_cutoff = now - timedelta(days=HISTORY_RETENTION_DAYS)
        for cov_key, cov in list(self.raw["coverage"].items()):
            dates = [
                item
                for item in cov.get("checked_dates") or []
                if (parsed := parse_date(item)) is not None and parsed >= today
            ]
            cov["checked_dates"] = sorted(set(dates))
            last_checked = parse_dt(cov.get("last_checked_at"))
            if last_checked is not None and (
                now - last_checked
            ) > timedelta(days=30):
                del self.raw["coverage"][cov_key]

        self.history = [
            item
            for item in self.history
            if (observed := parse_dt(item.get("ts"))) is not None
            and observed >= history_cutoff
        ]
        self.raw["runs"] = self.raw.get("runs", [])[-RUN_HISTORY_LIMIT:]
        self._checked_cache = None
        self._medians = None

    def save(self) -> None:
        payload = (
            json.dumps(self.raw, ensure_ascii=False, indent=2, sort_keys=True)
            + "\n"
        )
        _atomic_write(self.state_path, payload)
        lines = [
            json.dumps(item, ensure_ascii=False, sort_keys=True)
            for item in self.history
        ]
        history_payload = "\n".join(lines) + ("\n" if lines else "")
        _atomic_write(self.history_path, history_payload)


def make_cov_key(
    provider: str, origin: str, destination: str, cabin: str
) -> str:
    return coverage_key(provider, origin, destination, cabin)
