from __future__ import annotations

import uvicorn

from .config import Settings
from .service import create_app


def main() -> None:
    settings = Settings.from_env()
    app = create_app(settings=settings)
    config = uvicorn.Config(app, host=settings.host, port=settings.port)
    server = uvicorn.Server(config)
    app.state.bridge_lifecycle.set_shutdown_callback(lambda: setattr(server, "should_exit", True))
    server.run()


if __name__ == "__main__":
    main()
