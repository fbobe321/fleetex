"""Redis pub/sub subscriber — the consumer side of the bridge.

Subscribes to ``applied-ops`` (from document-updater) and ``editor-events`` (from
web/other real-time instances) and routes each message to the RealtimeServer's
dispatch methods, which fan out to the connected socket.io clients. This is what
makes document-updater's applied ops and web's file-tree events reach browsers.
"""

from __future__ import annotations

import asyncio
import logging

from .redis_bridge import APPLIED_OPS_CHANNEL, EDITOR_EVENTS_CHANNEL, parse_message

logger = logging.getLogger("real-time")


async def run_pubsub(redis, server) -> None:
    pubsub = redis.pubsub()
    await pubsub.subscribe(APPLIED_OPS_CHANNEL, EDITOR_EVENTS_CHANNEL)
    async for message in pubsub.listen():
        if message.get("type") != "message":
            continue
        try:
            channel = message["channel"]
            if isinstance(channel, bytes):
                channel = channel.decode("utf-8")
            data = parse_message(message["data"])
            if channel == APPLIED_OPS_CHANNEL or channel.startswith(APPLIED_OPS_CHANNEL + ":"):
                await server.dispatch_applied_ops(data)
            else:
                await server.dispatch_editor_event(data)
        except asyncio.CancelledError:
            raise
        except Exception as exc:  # noqa: BLE001 - a bad message must not kill the loop
            logger.warning("pubsub dispatch error: %s", exc)


def start_pubsub(redis, server) -> asyncio.Task:
    return asyncio.create_task(run_pubsub(redis, server))
