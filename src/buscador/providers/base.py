from __future__ import annotations

import logging
import random
import time
from abc import ABC, abstractmethod
from dataclasses import dataclass
from datetime import date, datetime

from ..config import AppConfig, ProviderConfig
from ..models import Cabin, ScanOutcome

logger = logging.getLogger(__name__)


class ProviderError(RuntimeError):
    """Falha recuperável de um provedor."""


class ProviderBlocked(ProviderError):
    """O provedor bloqueou o IP ou a sessão."""


class ProviderBudgetExceeded(ProviderError):
    """O orçamento de requisições foi atingido."""


class ProviderNotImplemented(ProviderError):
    """Adaptador ainda não implementado."""


@dataclass
class ScanContext:
    origin: str
    adults: int
    now: datetime
    timeout_seconds: float


class BaseProvider(ABC):
    code: str = ""

    def __init__(
        self, code: str, config: ProviderConfig, app: AppConfig
    ) -> None:
        self.code = code
        self.config = config
        self.app = app
        self.requests = 0
        self.navigations = 0
        self.started_at = datetime.now(app.tz)

    @abstractmethod
    def scan(
        self,
        destination: str,
        cabin: Cabin,
        window_start: date,
        window_end: date,
        ctx: ScanContext,
    ) -> ScanOutcome:
        """Busca uma janela de datas e devolve as oportunidades encontradas."""

    def sleep_between_requests(self) -> None:
        low, high = self.config.request_delay_ms
        delay = random.uniform(low, high) / 1000
        if delay > 0:
            time.sleep(delay)

    def sleep_between_navigations(self) -> None:
        delay = self.config.navigation_delay_seconds
        if delay > 0:
            time.sleep(delay)

    def close(self) -> None:
        """Libera browser/sessão; provedores sem estado não precisam fazer nada."""


class NotImplementedProvider(BaseProvider):
    def scan(
        self,
        destination: str,
        cabin: Cabin,
        window_start: date,
        window_end: date,
        ctx: ScanContext,
    ) -> ScanOutcome:
        raise ProviderNotImplemented(
            f"{self.code}: adaptador ainda não implementado. "
            "Rode o discovery/spike e consulte docs/recon/README.md."
        )
