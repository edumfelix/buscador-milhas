from __future__ import annotations

from ..config import LinkConfig


def enabled_links(links: dict[str, LinkConfig]) -> list[LinkConfig]:
    return [link for link in links.values() if link.enabled]
