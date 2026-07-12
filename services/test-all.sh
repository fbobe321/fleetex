#!/usr/bin/env bash
# Run every Python service's test suite in its own directory.
#
# Each service is an independent package with its own pytest config
# (asyncio_mode, testpaths). Running them from one rootdir makes pytest pick a
# single config and misfire, so we invoke each suite from its own directory.
set -euo pipefail
cd "$(dirname "$0")"

fail=0
for dir in */; do
  [ -f "${dir}pyproject.toml" ] || continue
  name="${dir%/}"
  echo "=== ${name} ==="
  if ! (cd "$dir" && python -m pytest -q); then
    fail=1
  fi
done
exit $fail
