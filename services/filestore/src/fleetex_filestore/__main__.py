"""Run the service: ``python -m fleetex_filestore``."""

import uvicorn

from .app import build_app
from .config import FilestoreConfig


def main() -> None:
    config = FilestoreConfig.from_env()
    host = "0.0.0.0"
    uvicorn.run(build_app(config), host=host, port=config.port)


if __name__ == "__main__":
    main()
