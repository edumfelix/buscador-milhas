from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, cast
from zoneinfo import ZoneInfo

import yaml

from .destinations import destination_city, destination_country, destination_name
from .models import CABINS, Cabin


class ConfigError(ValueError):
    """Erro de configuração legível para o usuário."""


@dataclass
class ProviderConfig:
    code: str
    name: str
    enabled: bool = True
    kind: str = "scrape"
    regions: list[str] = field(default_factory=lambda: ["domestic"])
    domestic_cabins: list[Cabin] = field(default_factory=lambda: ["Y"])
    international_cabins: list[Cabin] = field(default_factory=lambda: ["Y", "J"])
    window_days: int = 7
    sale_window_days: int = 180
    max_requests_per_run: int = 0
    max_navigations_per_run: int = 0
    request_delay_ms: tuple[int, int] = (4000, 8000)
    navigation_delay_seconds: float = 20.0
    timeout_seconds: float = 60.0
    deep_link: str = ""

    @property
    def budget(self) -> int:
        return max(self.max_requests_per_run, self.max_navigations_per_run, 1)


@dataclass
class LinkConfig:
    code: str
    name: str
    url: str
    note: str = ""
    enabled: bool = True


@dataclass
class AlertConfig:
    new_enabled: bool = True
    drop_min_pct: float = 10.0
    drop_min_miles: int = 1000
    suspicious_drop_pct: float = 60.0
    cooldown_hours: int = 24
    max_items_per_message: int = 10
    max_messages_per_run: int = 3


@dataclass
class SiteConfig:
    title: str = "Buscador de Milhas — Fortaleza (FOR)"
    max_cards: int = 200


@dataclass
class CoverageConfig:
    hot_destinations: list[str] = field(default_factory=list)
    max_age_hours: int = 168
    stale_after_hours: int = 26


@dataclass(frozen=True)
class Task:
    provider: str
    destination: str
    cabin: Cabin
    region: str


@dataclass
class AppConfig:
    root: Path
    origin: str
    horizon_days: int
    adults: int
    timezone: str
    cabins_domestic: list[Cabin]
    cabins_international: list[Cabin]
    destinations: dict[str, list[str]]
    providers: dict[str, ProviderConfig]
    links: dict[str, LinkConfig]
    alerting: AlertConfig
    site: SiteConfig
    coverage: CoverageConfig
    data_dir: Path
    templates_dir: Path
    static_dir: Path
    site_dir: Path

    @property
    def tz(self) -> ZoneInfo:
        return ZoneInfo(self.timezone)

    def destination_name(self, code: str) -> str:
        return destination_name(code)

    def destination_city(self, code: str) -> str:
        return destination_city(code)

    def destination_country(self, code: str) -> str:
        return destination_country(code)

    def program_label(self, code: str) -> str:
        if code in self.providers:
            return self.providers[code].name
        if code in self.links:
            return self.links[code].name
        return code

    def cabins_for(self, provider: ProviderConfig, region: str) -> list[Cabin]:
        if region == "domestic":
            return list(provider.domestic_cabins or self.cabins_domestic)
        if region == "international":
            return list(provider.international_cabins or self.cabins_international)
        return []

    def tasks(self) -> list[Task]:
        tasks: list[Task] = []
        for code, provider in self.providers.items():
            if not provider.enabled:
                continue
            for region in provider.regions:
                destinations = self.destinations.get(region, [])
                cabins = self.cabins_for(provider, region)
                for cabin in cabins:
                    for destination in destinations:
                        tasks.append(Task(code, destination, cabin, region))
        return tasks

    def enabled_links(self) -> list[LinkConfig]:
        return [link for link in self.links.values() if link.enabled]


def _require(condition: bool, message: str) -> None:
    if not condition:
        raise ConfigError(message)


def _as_list(value: Any, name: str) -> list[Any]:
    if value is None:
        return []
    if not isinstance(value, list):
        raise ConfigError(f"{name} deve ser uma lista")
    return value


def _airport(value: Any, name: str) -> str:
    code = str(value or "").strip().upper()
    _require(len(code) == 3 and code.isalpha(), f"{name} inválido: {value!r}")
    return code


def _cabin(value: Any, name: str) -> Cabin:
    cabin = str(value or "").strip().upper()
    _require(cabin in CABINS, f"{name} inválida: {value!r} (use Y ou J)")
    return cast(Cabin, cabin)


def _cabins(value: Any, name: str, default: list[Cabin]) -> list[Cabin]:
    raw = _as_list(value, name) if value is not None else list(default)
    return [_cabin(item, name) for item in raw]


def _regions(value: Any, name: str) -> list[str]:
    raw = _as_list(value, name) if value is not None else ["domestic"]
    regions = [str(item) for item in raw]
    for region in regions:
        _require(
            region in ("domestic", "international"),
            f"{name} inválida: {region}",
        )
    return regions


def _delay(value: Any, name: str) -> tuple[int, int]:
    raw = _as_list(value, name) if value is not None else [4000, 8000]
    _require(len(raw) == 2, f"{name} deve ter 2 valores")
    low, high = int(raw[0]), int(raw[1])
    _require(0 <= low <= high, f"{name} deve ter valores crescentes e não negativos")
    return low, high


def _path(value: Any, default: str, root: Path) -> Path:
    raw = Path(str(value or default))
    return raw if raw.is_absolute() else (root / raw).resolve()


def load_config(path: str | Path = "config.yaml") -> AppConfig:
    config_path = Path(path).resolve()
    if not config_path.exists():
        raise ConfigError(f"Arquivo de configuração não encontrado: {config_path}")
    try:
        raw = yaml.safe_load(config_path.read_text(encoding="utf-8")) or {}
    except yaml.YAMLError as exc:
        raise ConfigError(f"YAML inválido: {exc}") from exc
    _require(isinstance(raw, dict), "A configuração deve ser um objeto YAML")
    root = config_path.parent

    origin = _airport(raw.get("origin", "FOR"), "origin")
    horizon_days = int(raw.get("horizon_days", 180))
    _require(30 <= horizon_days <= 365, "horizon_days deve estar entre 30 e 365")
    adults = int(raw.get("adults", 1))
    _require(1 <= adults <= 9, "adults deve estar entre 1 e 9")
    timezone = str(raw.get("timezone", "America/Fortaleza"))
    try:
        ZoneInfo(timezone)
    except Exception as exc:
        raise ConfigError(f"timezone inválido: {timezone}") from exc

    cabins_raw = raw.get("cabins") or {}
    cabins_domestic = _cabins(
        cabins_raw.get("domestic", ["Y"]), "cabins.domestic", ["Y"]
    )
    cabins_international = _cabins(
        cabins_raw.get("international", ["Y", "J"]),
        "cabins.international",
        ["Y", "J"],
    )

    destinations_raw = raw.get("destinations") or {}
    destinations = {
        "domestic": [
            _airport(item, "destinations.domestic")
            for item in _as_list(
                destinations_raw.get("domestic", []), "destinations.domestic"
            )
        ],
        "international": [
            _airport(item, "destinations.international")
            for item in _as_list(
                destinations_raw.get("international", []),
                "destinations.international",
            )
        ],
    }
    _require(
        bool(destinations["domestic"] or destinations["international"]),
        "Informe ao menos um destino",
    )

    providers_raw = raw.get("providers") or {}
    _require(
        isinstance(providers_raw, dict) and bool(providers_raw),
        "Informe ao menos um provedor",
    )
    providers: dict[str, ProviderConfig] = {}
    for code, item in providers_raw.items():
        _require(isinstance(item, dict), f"providers.{code} deve ser um objeto")
        provider = ProviderConfig(
            code=str(code),
            name=str(item.get("name", code)),
            enabled=bool(item.get("enabled", True)),
            kind=str(item.get("kind", "scrape")),
            regions=_regions(
                item.get("regions", ["domestic"]), f"providers.{code}.regions"
            ),
            domestic_cabins=_cabins(
                item.get("domestic_cabins"),
                f"providers.{code}.domestic_cabins",
                cabins_domestic,
            ),
            international_cabins=_cabins(
                item.get("international_cabins"),
                f"providers.{code}.international_cabins",
                cabins_international,
            ),
            window_days=int(item.get("window_days", 7)),
            sale_window_days=int(item.get("sale_window_days", horizon_days)),
            max_requests_per_run=int(item.get("max_requests_per_run", 0)),
            max_navigations_per_run=int(item.get("max_navigations_per_run", 0)),
            request_delay_ms=_delay(
                item.get("request_delay_ms"),
                f"providers.{code}.request_delay_ms",
            ),
            navigation_delay_seconds=float(
                item.get("navigation_delay_seconds", 20)
            ),
            timeout_seconds=float(item.get("timeout_seconds", 60)),
            deep_link=str(item.get("deep_link", "")),
        )
        _require(
            provider.window_days >= 1,
            f"providers.{code}.window_days deve ser >= 1",
        )
        providers[provider.code] = provider

    links_raw = raw.get("links") or {}
    links: dict[str, LinkConfig] = {}
    for code, item in links_raw.items():
        if not isinstance(item, dict):
            continue
        links[str(code)] = LinkConfig(
            code=str(code),
            name=str(item.get("name", code)),
            url=str(item.get("url", "")),
            note=str(item.get("note", "")),
            enabled=bool(item.get("enabled", True)),
        )

    alert_raw = raw.get("alerting") or {}
    alerting = AlertConfig(
        new_enabled=bool(alert_raw.get("new_enabled", True)),
        drop_min_pct=float(alert_raw.get("drop_min_pct", 10)),
        drop_min_miles=int(alert_raw.get("drop_min_miles", 1000)),
        suspicious_drop_pct=float(alert_raw.get("suspicious_drop_pct", 60)),
        cooldown_hours=int(alert_raw.get("cooldown_hours", 24)),
        max_items_per_message=int(alert_raw.get("max_items_per_message", 10)),
        max_messages_per_run=int(alert_raw.get("max_messages_per_run", 3)),
    )
    site_raw = raw.get("site") or {}
    site = SiteConfig(
        title=str(
            site_raw.get(
                "title", "Buscador de Milhas — Fortaleza (FOR)"
            )
        ),
        max_cards=int(site_raw.get("max_cards", 200)),
    )
    coverage_raw = raw.get("coverage") or {}
    coverage = CoverageConfig(
        hot_destinations=[
            _airport(item, "coverage.hot_destinations")
            for item in _as_list(
                coverage_raw.get("hot_destinations", []),
                "coverage.hot_destinations",
            )
        ],
        max_age_hours=int(coverage_raw.get("max_age_hours", 168)),
        stale_after_hours=int(coverage_raw.get("stale_after_hours", 26)),
    )
    paths_raw = raw.get("paths") or {}
    data_dir = _path(paths_raw.get("data"), "data", root)
    templates_dir = _path(paths_raw.get("templates"), "templates", root)
    static_dir = _path(paths_raw.get("static"), "static", root)
    site_dir = _path(paths_raw.get("site"), "site", root)
    _require(
        templates_dir.exists(),
        f"Diretório de templates não encontrado: {templates_dir}",
    )
    _require(
        static_dir.exists(),
        f"Diretório de estáticos não encontrado: {static_dir}",
    )

    return AppConfig(
        root=root,
        origin=origin,
        horizon_days=horizon_days,
        adults=adults,
        timezone=timezone,
        cabins_domestic=cabins_domestic,
        cabins_international=cabins_international,
        destinations=destinations,
        providers=providers,
        links=links,
        alerting=alerting,
        site=site,
        coverage=coverage,
        data_dir=data_dir,
        templates_dir=templates_dir,
        static_dir=static_dir,
        site_dir=site_dir,
    )
