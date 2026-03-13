from __future__ import annotations

import uvicorn

from .config import Settings
from .service import create_app


def main() -> None:
    settings = Settings.from_env()
    app = create_app(settings=settings)
    uvicorn.run(app, host=settings.host, port=settings.port)


if __name__ == "__main__":
    main()
