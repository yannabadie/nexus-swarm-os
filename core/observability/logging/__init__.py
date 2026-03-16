"""
Logging module for NEXUS V7

Exports:
- NexusLogger: Main logger class
- LogLevel: Log level enum
- EventType: Event type enum
- init_logger: Initialize global logger
- get_logger: Get global logger instance
- cleanup_old_logs: Cleanup old log files
- get_driver_logger: Get lightweight driver logger (V8.4.5)
- configure_driver_logging: Configure driver log level (V8.4.5)
"""

from .driver_logger import DriverLogger, configure_driver_logging, get_driver_logger
from .logger_v7 import EventType, LogLevel, NexusLogger, cleanup_old_logs, get_logger, init_logger

__all__ = [
    "NexusLogger",
    "LogLevel",
    "EventType",
    "init_logger",
    "get_logger",
    "cleanup_old_logs",
    "get_driver_logger",
    "configure_driver_logging",
    "DriverLogger",
]
