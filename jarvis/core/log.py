"""Structured logging — structlog to file + EventBus → in-UI activity panel."""
from __future__ import annotations

import logging
from pathlib import Path

from jarvis.core import config
from jarvis.core.bus import BUS

try:
    import structlog
    _HAS_STRUCTLOG = True
except ImportError:          # graceful degradation — stdlib logging only
    structlog = None
    _HAS_STRUCTLOG = False

_configured = False


def _bus_processor(logger, method_name, event_dict):
    BUS.publish(
        "log",
        level=method_name.upper(),
        source=event_dict.get("source", "core"),
        message=event_dict.get("event", ""),
        extra={k: v for k, v in event_dict.items()
               if k not in ("event", "source", "timestamp", "level")},
    )
    return event_dict


def setup() -> None:
    global _configured
    if _configured:
        return
    _configured = True

    log_dir = config.resolve_path(config.get("logging.dir", "logs"))
    log_dir.mkdir(parents=True, exist_ok=True)
    log_file = log_dir / config.get("logging.file", "jarvis.log")
    level = getattr(logging, config.get("logging.level", "INFO"), logging.INFO)

    handler = logging.FileHandler(log_file, encoding="utf-8")
    handler.setFormatter(logging.Formatter("%(message)s"))
    root = logging.getLogger("jarvis")
    root.setLevel(level)
    root.addHandler(handler)
    root.propagate = False

    if _HAS_STRUCTLOG:
        structlog.configure(
            processors=[
                structlog.processors.TimeStamper(fmt="iso"),
                structlog.processors.add_log_level,
                _bus_processor,
                structlog.processors.JSONRenderer(),
            ],
            logger_factory=structlog.stdlib.LoggerFactory(),
            wrapper_class=structlog.stdlib.BoundLogger,
            cache_logger_on_first_use=True,
        )


def get(source: str = "core"):
    """Return a bound logger. Works with or without structlog installed."""
    setup()
    if _HAS_STRUCTLOG:
        return structlog.get_logger("jarvis").bind(source=source)
    return _FallbackLogger(source)


class _FallbackLogger:
    def __init__(self, source: str):
        self._source = source
        self._log = logging.getLogger("jarvis")

    def _emit(self, level: str, event: str, **kw):
        self._log.log(getattr(logging, level.upper(), logging.INFO),
                      f"[{self._source}] {event} {kw if kw else ''}")
        BUS.publish("log", level=level.upper(), source=self._source,
                    message=event, extra=kw)

    def info(self, event, **kw):    self._emit("INFO", event, **kw)
    def warning(self, event, **kw): self._emit("WARNING", event, **kw)
    def error(self, event, **kw):   self._emit("ERROR", event, **kw)
    def debug(self, event, **kw):   self._emit("DEBUG", event, **kw)
