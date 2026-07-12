"""Structured JSON logging, matching the shape Overleaf services emit.

Overleaf uses bunyan-style JSON logs. We emit compatible one-line JSON so
existing log tooling keeps working when a service is flipped to Python.
"""

from __future__ import annotations

import json
import logging
import sys
import time


class JsonFormatter(logging.Formatter):
    def __init__(self, service_name: str) -> None:
        super().__init__()
        self.service_name = service_name

    def format(self, record: logging.LogRecord) -> str:
        payload = {
            "time": time.strftime("%Y-%m-%dT%H:%M:%S", time.gmtime(record.created)),
            "level": record.levelname.lower(),
            "name": self.service_name,
            "msg": record.getMessage(),
        }
        if record.exc_info:
            payload["err"] = self.formatException(record.exc_info)
        # Attach any structured extras passed via logger.info(..., extra={...}).
        for key, value in record.__dict__.items():
            if key not in _RESERVED and not key.startswith("_"):
                payload[key] = value
        return json.dumps(payload, default=str)


# Standard LogRecord attributes we should not duplicate into the payload.
_RESERVED = set(
    logging.makeLogRecord({}).__dict__.keys()
) | {"message", "asctime"}


def configure_logging(service_name: str, level: str = "info") -> logging.Logger:
    """Install the JSON formatter on the root logger and return the service logger."""
    handler = logging.StreamHandler(sys.stdout)
    handler.setFormatter(JsonFormatter(service_name))
    root = logging.getLogger()
    root.handlers[:] = [handler]
    root.setLevel(getattr(logging, level.upper(), logging.INFO))
    return logging.getLogger(service_name)
