"""Run the service: ``python -m fleetex_document_updater`` (HTTP + dispatchers)."""

import uvicorn

from .app import build_app
from .config import DocUpdaterConfig
from .dispatch import start_dispatchers


def main() -> None:
    config = DocUpdaterConfig.from_env()
    app = build_app(config)

    @app.on_event("startup")
    async def _start_dispatchers():
        start_dispatchers(app.state.redis, app.state.updater, config.dispatcher_count)

    uvicorn.run(app, host="0.0.0.0", port=config.port)


if __name__ == "__main__":
    main()
