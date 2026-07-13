"""Run the service: ``python -m fleetex_project_history``."""

import uvicorn

from fleetex_service_kit import Settings

from .app import build_app


def main() -> None:
    settings = Settings.from_env("project-history", default_port=3054)
    uvicorn.run(build_app(settings), host=settings.host, port=settings.port)


if __name__ == "__main__":
    main()
