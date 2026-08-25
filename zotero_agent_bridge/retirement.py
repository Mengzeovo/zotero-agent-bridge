from __future__ import annotations

import sys


RETIREMENT_MESSAGE = (
    "This integration surface was retired in Zotero Pi Assistant 0.4.0-beta. "
    "Use the Zotero add-on's built-in Pi literature assistant instead."
)


def retired_main(surface: str | None = None) -> int:
    label = f" ({surface})" if surface else ""
    print(f"Zotero Pi Assistant: feature_retired{label}: {RETIREMENT_MESSAGE}", file=sys.stderr)
    return 2
