from __future__ import annotations

from ..config import AppConfig, ProviderConfig
from .azul import AzulProvider
from .base import BaseProvider, NotImplementedProvider
from .demo import DemoProvider
from .smiles import SmilesProvider

__all__ = [
    "BaseProvider",
    "build_provider",
]


def build_provider(
    code: str,
    config: ProviderConfig,
    app: AppConfig,
    *,
    demo: bool = False,
) -> BaseProvider:
    if demo:
        return DemoProvider(code, config, app)
    if code == "smiles":
        return SmilesProvider(code, config, app)
    if code == "azul":
        return AzulProvider(code, config, app)
    return NotImplementedProvider(code, config, app)
