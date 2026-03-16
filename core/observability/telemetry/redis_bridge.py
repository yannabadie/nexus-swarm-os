"""
NEXUS V10 CEREBRO - Redis Log Bridge

Bridges Python logging to Redis pub/sub using Queue + Thread pattern.

Architecture:
- Queue(maxsize=10000) for buffering log records
- Daemon thread drains queue to Redis synchronously
- emit() is non-blocking (put_nowait), drops on overflow
- Graceful degradation: if Redis unavailable, logs are dropped

Why Queue + Thread (not asyncio.create_task):
- logging.Handler.emit() must be synchronous
- asyncio.create_task() in emit() can lose data on shutdown
- Thread + Queue provides reliable buffering and backpressure

Usage:
    handler = RedisLogHandler(
        redis_url="redis://localhost:6379",
        tenant_id="system",
        workspace_id="logs"
    )
    handler.start()
    logging.getLogger("myapp").addHandler(handler)

    # On shutdown
    handler.stop()
"""

import contextlib
import json
import logging
import queue
import threading
import time
from datetime import UTC, datetime
from typing import Any
from uuid import uuid4


class RedisLogHandler(logging.Handler):
    """
    Python logging handler that bridges logs to Redis pub/sub.

    Thread-safe, non-blocking emit(), graceful degradation.
    """

    def __init__(
        self,
        redis_url: str = "redis://localhost:6379",
        tenant_id: str = "system",
        workspace_id: str = "logs",
        queue_size: int = 10000,
        level: int = logging.INFO,
    ):
        """
        Initialize RedisLogHandler.

        Args:
            redis_url: Redis connection URL
            tenant_id: Tenant identifier for channel routing
            workspace_id: Workspace identifier
            queue_size: Max queue size before dropping logs
            level: Minimum log level to handle
        """
        super().__init__(level)

        self._redis_url = redis_url
        self._tenant_id = tenant_id
        self._workspace_id = workspace_id
        self._queue: queue.Queue = queue.Queue(maxsize=queue_size)
        self._running = False
        self._thread: threading.Thread | None = None
        self._redis: Any | None = None  # redis.Redis (sync)

        # Stats
        self._stats = {
            "queued": 0,
            "published": 0,
            "dropped": 0,
            "errors": 0,
        }

    def start(self) -> bool:
        """
        Start the background worker thread.

        Returns:
            True if started successfully
        """
        if self._running:
            return True

        self._running = True
        self._thread = threading.Thread(target=self._worker, daemon=True, name="RedisLogHandler-Worker")
        self._thread.start()
        return True

    def stop(self, timeout: float = 5.0) -> None:
        """
        Stop the background worker thread gracefully.

        Args:
            timeout: Max seconds to wait for queue drain
        """
        if not self._running:
            return

        self._running = False

        if self._thread:
            self._thread.join(timeout=timeout)
            self._thread = None

        if self._redis:
            with contextlib.suppress(Exception):
                self._redis.close()
            self._redis = None

    def emit(self, record: logging.LogRecord) -> None:
        """
        Emit a log record (non-blocking).

        Args:
            record: LogRecord to emit

        Note: Drops record if queue is full (graceful degradation)
        """
        try:
            # Format the record
            msg = self.format(record)

            # Build payload
            payload = {
                "level": record.levelname,
                "message": msg,
                "logger": record.name,
                "timestamp": datetime.now(UTC).isoformat(),
                "funcName": record.funcName,
                "lineno": record.lineno,
            }

            # Add exception info if present
            if record.exc_info:
                payload["exception"] = self.formatException(record.exc_info)

            # Non-blocking queue put
            self._queue.put_nowait(payload)
            self._stats["queued"] += 1

        except queue.Full:
            self._stats["dropped"] += 1
        except Exception:
            self._stats["errors"] += 1

    def _worker(self) -> None:
        """Background worker thread: drain queue to Redis."""
        # Connect to Redis
        try:
            import redis

            self._redis = redis.Redis.from_url(
                self._redis_url,
                encoding="utf-8",
                decode_responses=True,
                socket_connect_timeout=5.0,
                socket_timeout=5.0,
            )
            # Test connection
            self._redis.ping()
        except ImportError:
            logging.warning("RedisLogHandler: redis package not installed")
            return
        except Exception as e:
            logging.warning(f"RedisLogHandler: Failed to connect to Redis: {e}")
            return

        # Worker loop
        while self._running or not self._queue.empty():
            try:
                # Block with timeout to allow checking _running flag
                payload = self._queue.get(timeout=1.0)

                # Build event
                event_data = {
                    "event_type": "system.log",
                    "tenant_id": self._tenant_id,
                    "workspace_id": self._workspace_id,
                    "payload": payload,
                    "timestamp": payload.get("timestamp", datetime.now(UTC).isoformat()),
                    "event_id": uuid4().hex[:12],
                }

                # Publish to Redis
                channel = f"nexus:{self._tenant_id}:{self._workspace_id}:system.log"
                self._redis.publish(channel, json.dumps(event_data, ensure_ascii=False))
                self._stats["published"] += 1

            except queue.Empty:
                continue
            except Exception:
                self._stats["errors"] += 1
                # Don't log here - could cause infinite loop!

    def get_stats(self) -> dict[str, Any]:
        """
        Get handler statistics.

        Returns:
            Dict with queued, published, dropped, errors counts
        """
        return {
            **self._stats,
            "queue_size": self._queue.qsize(),
            "running": self._running,
            "connected": self._redis is not None,
        }

    def flush(self) -> None:
        """Flush pending logs (blocks until queue is empty or timeout)."""
        timeout = 5.0
        start = time.time()
        while not self._queue.empty() and (time.time() - start) < timeout:
            time.sleep(0.1)

    def close(self) -> None:
        """Close the handler."""
        self.stop()
        super().close()


# =============================================================================
# Factory Function
# =============================================================================


def create_redis_log_handler(
    tenant_id: str,
    workspace_id: str,
    redis_url: str = "redis://localhost:6379",
    level: int = logging.INFO,
) -> RedisLogHandler:
    """
    Create and start a RedisLogHandler.

    Args:
        tenant_id: Tenant identifier
        workspace_id: Workspace identifier
        redis_url: Redis connection URL
        level: Minimum log level

    Returns:
        Started RedisLogHandler instance
    """
    handler = RedisLogHandler(
        redis_url=redis_url,
        tenant_id=tenant_id,
        workspace_id=workspace_id,
        level=level,
    )
    handler.start()
    return handler
