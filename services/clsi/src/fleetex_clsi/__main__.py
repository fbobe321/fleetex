"""Run the service: ``python -m fleetex_clsi`` (uses the real TeX toolchain)."""

import uvicorn

from .app import build_app
from .config import ClsiConfig


def main() -> None:
    config = ClsiConfig.from_env()
    uvicorn.run(build_app(config), host="0.0.0.0", port=config.port)


if __name__ == "__main__":
    main()
