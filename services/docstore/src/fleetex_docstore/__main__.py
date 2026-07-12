"""Run the service: ``python -m fleetex_docstore``."""

import uvicorn

from .app import build_app
from .config import DocstoreConfig


def main() -> None:
    config = DocstoreConfig.from_env()
    uvicorn.run(build_app(config), host="0.0.0.0", port=config.port)


if __name__ == "__main__":
    main()
