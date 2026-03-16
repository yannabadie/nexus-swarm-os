"""
Driver Logger - Lightweight logging for driver modules.

NEXUS V8.4.5 - Bug Fixes Phase

Provides a simple logging interface for driver modules that may be
initialized before the main NexusLogger. Falls back to Python's
standard logging module.

Usage:
    from core.observability.logging.driver_logger import get_driver_logger

    logger = get_driver_logger("gemini_driver")
    logger.debug("Invoking Gemini", model="gemini-3-pro")
    logger.warning("Rate limited, retrying", attempt=2)
"""

import logging
import os
import sys
from typing import Any

# Configure basic logging format
_LOG_FORMAT = "[%(levelname)s] %(name)s: %(message)s"
_DATE_FORMAT = "%H:%M:%S"


# Get log level from environment (respects .env LOG_LEVEL)
def _get_default_level() -> int:
    """Get default log level from environment."""
    level_name = os.getenv("LOG_LEVEL", "INFO").upper()
    return getattr(logging, level_name, logging.INFO)


def _format_extras(extras: dict[str, Any]) -> str:
    """Format extra parameters as key=value pairs."""
    if not extras:
        return ""
    pairs = [f"{k}={v}" for k, v in extras.items() if not k.startswith("_")]
    return " | " + ", ".join(pairs) if pairs else ""


class DriverLogger:
    """
    Lightweight logger for driver modules.

    Wraps Python's logging module with a consistent interface
    and support for structured extra parameters.
    """

    def __init__(self, name: str, level: int = None):
        """
        Initialize driver logger.

        Args:
            name: Logger name (e.g., "gemini_driver")
            level: Logging level (default: from LOG_LEVEL env var or INFO)
        """
        if level is None:
            level = _get_default_level()
        self.name = name
        self._logger = logging.getLogger(f"nexus.drivers.{name}")
        self._logger.setLevel(level)

        # Add handler if not already configured
        if not self._logger.handlers:
            handler = logging.StreamHandler(sys.stderr)
            handler.setLevel(level)
            formatter = logging.Formatter(_LOG_FORMAT, _DATE_FORMAT)
            handler.setFormatter(formatter)
            self._logger.addHandler(handler)
            # Prevent propagation to root logger (avoid duplicate logs)
            self._logger.propagate = False

    def debug(self, message: str, **kwargs: Any) -> None:
        """Log debug message with optional extras."""
        self._logger.debug(f"{message}{_format_extras(kwargs)}")

    def info(self, message: str, **kwargs: Any) -> None:
        """Log info message with optional extras."""
        self._logger.info(f"{message}{_format_extras(kwargs)}")

    def warning(self, message: str, **kwargs: Any) -> None:
        """Log warning message with optional extras."""
        self._logger.warning(f"{message}{_format_extras(kwargs)}")

    def error(self, message: str, **kwargs: Any) -> None:
        """Log error message with optional extras."""
        self._logger.error(f"{message}{_format_extras(kwargs)}")

    def critical(self, message: str, **kwargs: Any) -> None:
        """Log critical message with optional extras."""
        self._logger.critical(f"{message}{_format_extras(kwargs)}")

    def set_level(self, level: int) -> None:
        """Change log level."""
        self._logger.setLevel(level)
        for handler in self._logger.handlers:
            handler.setLevel(level)


# Cache of driver loggers
_driver_loggers: dict[str, DriverLogger] = {}


def get_driver_logger(name: str) -> DriverLogger:
    """
    Get or create a driver logger.

    Args:
        name: Logger name (e.g., "gemini_driver", "claude_driver")

    Returns:
        DriverLogger instance
    """
    if name not in _driver_loggers:
        _driver_loggers[name] = DriverLogger(name)
    return _driver_loggers[name]


def configure_driver_logging(level: str = "INFO") -> None:
    """
    Configure logging level for all driver loggers.

    Args:
        level: Log level string (DEBUG, INFO, WARNING, ERROR, CRITICAL)
    """
    log_level = getattr(logging, level.upper(), logging.INFO)
    for logger in _driver_loggers.values():
        logger.set_level(log_level)
