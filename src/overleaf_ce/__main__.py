"""Enable ``python -m overleaf_ce``."""

from .cli import main

if __name__ == "__main__":
    raise SystemExit(main())
