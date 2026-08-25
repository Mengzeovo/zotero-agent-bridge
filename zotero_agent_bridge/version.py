from __future__ import annotations

import os


BRIDGE_VERSION = "0.4.1-beta"
PRODUCT_NAME = "Zotero Pi Assistant"
PRODUCT_SCOPE = "zotero-pi-only"
LIFECYCLE_PROTOCOL_VERSION = 2
DEFAULT_DISTRIBUTION = "source"


def bridge_distribution() -> str:
    value = os.environ.get("ZOTERO_AGENT_BRIDGE_DISTRIBUTION", DEFAULT_DISTRIBUTION).strip()
    return value or DEFAULT_DISTRIBUTION
