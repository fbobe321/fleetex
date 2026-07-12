"""Run the service: ``python -m fleetex_realtime`` (socket.io + HTTP via ASGI)."""

import uvicorn

from .app import build_asgi
from .config import RealtimeConfig


def main() -> None:
    config = RealtimeConfig.from_env()
    uvicorn.run(build_asgi(config), host="0.0.0.0", port=config.port)


if __name__ == "__main__":
    main()
