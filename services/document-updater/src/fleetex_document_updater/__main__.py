"""Run the service: ``python -m fleetex_document_updater`` (HTTP + dispatchers)."""

import uvicorn

from .app import build_app
from .config import DocUpdaterConfig


def main() -> None:
    config = DocUpdaterConfig.from_env()
    app = build_app(config, with_workers=True)  # start the BLPOP dispatchers on startup
    uvicorn.run(app, host="0.0.0.0", port=config.port)


if __name__ == "__main__":
    main()
