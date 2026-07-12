"""Mongo and Redis client factories.

Clients are created lazily (no network I/O until first use), so importing and
constructing them is safe in tests without a running database.
"""

from __future__ import annotations

from urllib.parse import urlparse

from motor.motor_asyncio import AsyncIOMotorClient, AsyncIOMotorDatabase
from redis import asyncio as aioredis


def database_name_from_url(mongo_url: str, default: str = "sharelatex") -> str:
    """Extract the database name from a mongodb:// URL (Overleaf uses 'sharelatex')."""
    path = urlparse(mongo_url).path.lstrip("/")
    return path or default


def create_mongo_client(mongo_url: str) -> AsyncIOMotorClient:
    return AsyncIOMotorClient(mongo_url, tz_aware=True)


def get_database(client: AsyncIOMotorClient, mongo_url: str) -> AsyncIOMotorDatabase:
    return client[database_name_from_url(mongo_url)]


def create_redis(redis_url: str) -> "aioredis.Redis":
    # decode_responses=False: Overleaf stores some binary values in Redis.
    return aioredis.from_url(redis_url, decode_responses=False)
