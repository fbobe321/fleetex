"""DispatchManager — BLPOP the pending-updates-list shards and process (port of
DispatchManager.js). Shard 0 -> ``pending-updates-list``; shard N -> ``-N``.
Real-time RPUSHes ``projectId:docId`` here after queueing the update onto
``PendingUpdates:{docId}``.
"""

from __future__ import annotations

import asyncio
import logging

logger = logging.getLogger("document-updater")


async def run_dispatcher(redis, updater, shard: int) -> None:
    key = "pending-updates-list" if shard == 0 else f"pending-updates-list-{shard}"
    while True:
        try:
            # finite timeout so a blocked read never fights the socket timeout;
            # on None (nothing queued) just loop and block again.
            result = await redis.blpop(key, timeout=5)
            if not result:
                continue
            _list_name, doc_key = result
            project_id, _, doc_id = doc_key.partition(":")
            await updater.process_pending(project_id, doc_id)
        except asyncio.CancelledError:
            raise
        except Exception as exc:  # noqa: BLE001 - a bad update must not kill the worker
            logger.warning("dispatcher error: %s", exc)


def start_dispatchers(redis, updater, count: int) -> list:
    return [asyncio.create_task(run_dispatcher(redis, updater, shard)) for shard in range(count)]
