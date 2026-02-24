"""Structured logging configuration with Rich console handler."""

from __future__ import annotations

import logging

from rich.console import Console
from rich.logging import RichHandler

_configured = False

console = Console(stderr=True)


def setup_logging(level: str = "INFO") -> None:
    """Configure the root logger with a Rich handler.

    Safe to call multiple times; only the first invocation applies.
    """
    global _configured
    if _configured:
        return
    _configured = True

    numeric_level = getattr(logging, level.upper(), logging.INFO)

    rich_handler = RichHandler(
        console=console,
        show_time=True,
        show_path=False,
        markup=True,
        rich_tracebacks=True,
        tracebacks_show_locals=False,
    )
    rich_handler.setLevel(numeric_level)

    logging.basicConfig(
        level=numeric_level,
        format="%(message)s",
        datefmt="[%X]",
        handlers=[rich_handler],
        force=True,
    )

    logging.getLogger("urllib3").setLevel(logging.WARNING)
    logging.getLogger("selenium").setLevel(logging.WARNING)
    logging.getLogger("httpx").setLevel(logging.WARNING)
    logging.getLogger("httpcore").setLevel(logging.WARNING)
    logging.getLogger("anthropic").setLevel(logging.WARNING)


def get_logger(name: str) -> logging.Logger:
    """Return a module-level logger, ensuring logging is configured."""
    setup_logging()
    return logging.getLogger(name)
