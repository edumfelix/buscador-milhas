from __future__ import annotations

from datetime import date

from ..models import Cabin, ScanOutcome
from .base import BaseProvider, ProviderNotImplemented, ScanContext


class AzulProvider(BaseProvider):
    """Adaptador da Azul Fidelidade.

    O recon indica Playwright com interceptação da requisição da própria
    página, lotes de 6 datas e limite de ~8 navegações por IP. A implementação
    real fica para o M3; até lá, devolve "não implementado".
    """

    def scan(
        self,
        destination: str,
        cabin: Cabin,
        window_start: date,
        window_end: date,
        ctx: ScanContext,
    ) -> ScanOutcome:
        raise ProviderNotImplemented(
            "Azul: adaptador pendente do spike (M3). "
            "Requer Playwright e respeito ao limite de navegações por IP."
        )
