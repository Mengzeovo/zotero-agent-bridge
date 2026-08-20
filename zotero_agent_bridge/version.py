from __future__ import annotations

import os


BRIDGE_VERSION = "0.3.3"
LIFECYCLE_PROTOCOL_VERSION = 1
DEFAULT_DISTRIBUTION = "source"


def bridge_distribution() -> str:
    value = os.environ.get("ZOTERO_AGENT_BRIDGE_DISTRIBUTION", DEFAULT_DISTRIBUTION).strip()
    return value or DEFAULT_DISTRIBUTION
