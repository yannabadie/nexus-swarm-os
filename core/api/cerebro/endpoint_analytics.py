"""
Endpoint Analytics - Track API endpoint performance metrics.

V12.4 COGNITIVE BOOST

Tracks per-endpoint performance:
- Request counts and throughput per endpoint
- Latency distribution and averages
- Error rates and error-prone endpoint detection
- Slowest endpoint identification

Usage:
    from core.api.cerebro.endpoint_analytics import get_endpoint_analytics

    analytics = get_endpoint_analytics()
    analytics.record_request("/api/users", method="GET", latency_ms=45.2)
    analytics.record_request("/api/auth/login", method="POST", status_code=401,
                             latency_ms=120.0, error=True, error_type="Unauthorized")
    profile = analytics.get_endpoint_profile("/api/users", method="GET")
    stats = analytics.get_stats()
"""

from __future__ import annotations

import dataclasses
import logging
import threading
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any

_logger = logging.getLogger(__name__)


# =============================================================================
# Constants
# =============================================================================

MAX_REQUESTS: int = 50000


# =============================================================================
# Types
# =============================================================================


@dataclass
class EndpointRequestRecord:
    """Record of a single API endpoint request.

    Attributes:
        request_id: Unique identifier for the request (auto-generated).
        endpoint: The API endpoint path (e.g. "/api/users").
        method: HTTP method (GET, POST, PUT, DELETE, etc.).
        status_code: HTTP response status code.
        latency_ms: Request latency in milliseconds.
        error: Whether the request resulted in an error.
        error_type: Type or description of error if applicable.
        timestamp: ISO 8601 timestamp of the request.
    """

    request_id: str = ""
    endpoint: str = ""
    method: str = "GET"
    status_code: int = 200
    latency_ms: float = 0.0
    error: bool = False
    error_type: str = ""
    timestamp: str = ""

    def to_dict(self) -> dict[str, Any]:
        """Serialize to dictionary.

        Returns:
            Dict representation of the request record.
        """
        return dataclasses.asdict(self)


@dataclass
class EndpointProfile:
    """Aggregated performance profile for a specific endpoint+method pair.

    Attributes:
        endpoint: The API endpoint path.
        method: HTTP method.
        total_requests: Total number of requests recorded.
        error_count: Number of requests that resulted in errors.
        total_latency_ms: Cumulative latency across all requests.
    """

    endpoint: str = ""
    method: str = "GET"
    total_requests: int = 0
    error_count: int = 0
    total_latency_ms: float = 0.0

    @property
    def error_rate(self) -> float:
        """Compute error rate as ratio of errors to total requests.

        Returns:
            Error rate between 0.0 and 1.0, or 0.0 if no requests.
        """
        if self.total_requests > 0:
            return self.error_count / self.total_requests
        return 0.0

    @property
    def avg_latency_ms(self) -> float:
        """Compute average latency per request in milliseconds.

        Returns:
            Average latency, or 0.0 if no requests.
        """
        if self.total_requests > 0:
            return self.total_latency_ms / self.total_requests
        return 0.0

    def to_dict(self) -> dict[str, Any]:
        """Serialize to dictionary including computed properties.

        Returns:
            Dict representation with error_rate and avg_latency_ms included.
        """
        result = dataclasses.asdict(self)
        result["error_rate"] = round(self.error_rate, 4)
        result["avg_latency_ms"] = round(self.avg_latency_ms, 2)
        return result


@dataclass
class EndpointAnalyticsStats:
    """Overall endpoint analytics statistics.

    Attributes:
        total_requests: Total number of requests across all endpoints.
        unique_endpoints: Number of distinct endpoint+method pairs tracked.
        overall_error_rate: Aggregate error rate across all requests.
        avg_latency_ms: Average latency across all requests.
    """

    total_requests: int = 0
    unique_endpoints: int = 0
    overall_error_rate: float = 0.0
    avg_latency_ms: float = 0.0

    def to_dict(self) -> dict[str, Any]:
        """Serialize to dictionary.

        Returns:
            Dict representation of the analytics stats.
        """
        return dataclasses.asdict(self)


# =============================================================================
# Endpoint Analytics
# =============================================================================


class EndpointAnalytics:
    """Track API endpoint performance with bounded request history.

    Features:
    - Record requests with endpoint, method, status, latency, and error info
    - Per-endpoint aggregated profiles (error rate, avg latency)
    - FIFO eviction when request history exceeds max_requests
    - Identify slowest and most error-prone endpoints
    - Thread-safe via threading.Lock()

    Args:
        max_requests: Maximum number of request records to retain.
    """

    def __init__(self, max_requests: int = MAX_REQUESTS) -> None:
        self._max_requests = max_requests
        self._requests: list[EndpointRequestRecord] = []
        self._profiles: dict[str, EndpointProfile] = {}
        self._counter: int = 1
        self._lock = threading.Lock()

    # =========================================================================
    # Recording
    # =========================================================================

    def record_request(
        self,
        endpoint: str,
        method: str = "GET",
        status_code: int = 200,
        latency_ms: float = 0.0,
        error: bool = False,
        error_type: str = "",
    ) -> EndpointRequestRecord:
        """Record an API endpoint request and update the endpoint profile.

        Args:
            endpoint: The API endpoint path (e.g. "/api/users").
            method: HTTP method (GET, POST, PUT, DELETE, etc.).
            status_code: HTTP response status code.
            latency_ms: Request latency in milliseconds.
            error: Whether the request resulted in an error.
            error_type: Type or description of error if applicable.

        Returns:
            The created EndpointRequestRecord.
        """
        with self._lock:
            request_id = f"req_{self._counter:06d}"
            self._counter += 1

            record = EndpointRequestRecord(
                request_id=request_id,
                endpoint=endpoint,
                method=method,
                status_code=status_code,
                latency_ms=latency_ms,
                error=error,
                error_type=error_type,
                timestamp=datetime.now(UTC).isoformat(),
            )

            # FIFO eviction
            if len(self._requests) >= self._max_requests:
                self._requests.pop(0)
            self._requests.append(record)

            # Update profile
            self._update_profile(record)

            return record

    def _update_profile(self, record: EndpointRequestRecord) -> None:
        """Update the aggregated profile for the endpoint in the record.

        Must be called while holding self._lock.

        Args:
            record: The request record to aggregate into the profile.
        """
        key = f"{record.method}:{record.endpoint}"
        if key not in self._profiles:
            self._profiles[key] = EndpointProfile(
                endpoint=record.endpoint,
                method=record.method,
            )
        profile = self._profiles[key]
        profile.total_requests += 1
        profile.total_latency_ms += record.latency_ms
        if record.error:
            profile.error_count += 1

    # =========================================================================
    # Profile Queries
    # =========================================================================

    def get_endpoint_profile(self, endpoint: str, method: str = "GET") -> EndpointProfile | None:
        """Get the aggregated profile for a specific endpoint and method.

        Args:
            endpoint: The API endpoint path.
            method: HTTP method.

        Returns:
            The EndpointProfile if found, None otherwise.
        """
        with self._lock:
            key = f"{method}:{endpoint}"
            return self._profiles.get(key)

    def get_all_profiles(self) -> list[EndpointProfile]:
        """Return all endpoint profiles sorted by total_requests descending.

        Returns:
            List of EndpointProfile instances.
        """
        with self._lock:
            return sorted(
                self._profiles.values(),
                key=lambda p: p.total_requests,
                reverse=True,
            )

    def get_slowest_endpoints(self, limit: int = 5) -> list[EndpointProfile]:
        """Return the slowest endpoints by average latency.

        Args:
            limit: Maximum number of profiles to return.

        Returns:
            List of EndpointProfile instances sorted by avg_latency_ms descending.
        """
        with self._lock:
            return sorted(
                self._profiles.values(),
                key=lambda p: p.avg_latency_ms,
                reverse=True,
            )[:limit]

    def get_error_prone_endpoints(self, min_requests: int = 3, threshold: float = 0.1) -> list[EndpointProfile]:
        """Return endpoints with error rates exceeding the threshold.

        Filters to endpoints with at least min_requests total requests
        and an error_rate strictly greater than threshold.

        Args:
            min_requests: Minimum number of requests required to be considered.
            threshold: Error rate threshold (exclusive).

        Returns:
            List of EndpointProfile instances matching the criteria.
        """
        with self._lock:
            return [p for p in self._profiles.values() if p.total_requests >= min_requests and p.error_rate > threshold]

    # =========================================================================
    # Request Queries
    # =========================================================================

    def get_recent_requests(self, limit: int = 10, endpoint: str | None = None) -> list[EndpointRequestRecord]:
        """Return the most recent request records.

        Args:
            limit: Maximum number of records to return.
            endpoint: If provided, filter to this endpoint path only.

        Returns:
            List of EndpointRequestRecord instances, most recent last.
        """
        with self._lock:
            if endpoint is not None:
                filtered = [r for r in self._requests if r.endpoint == endpoint]
            else:
                filtered = list(self._requests)
            return filtered[-limit:]

    def list_endpoints(self) -> list[str]:
        """Return sorted list of all tracked endpoint keys (METHOD:path).

        Returns:
            Sorted list of profile keys.
        """
        with self._lock:
            return sorted(self._profiles.keys())

    # =========================================================================
    # Statistics
    # =========================================================================

    def get_stats(self) -> EndpointAnalyticsStats:
        """Compute overall endpoint analytics statistics.

        Returns:
            EndpointAnalyticsStats with aggregate metrics.
        """
        with self._lock:
            total = len(self._requests)
            unique = len(self._profiles)
            errors = sum(1 for r in self._requests if r.error)
            total_latency = sum(r.latency_ms for r in self._requests)

            return EndpointAnalyticsStats(
                total_requests=total,
                unique_endpoints=unique,
                overall_error_rate=(errors / total if total > 0 else 0.0),
                avg_latency_ms=(total_latency / total if total > 0 else 0.0),
            )

    # =========================================================================
    # State
    # =========================================================================

    @property
    def request_count(self) -> int:
        """Number of request records currently stored."""
        with self._lock:
            return len(self._requests)

    def clear(self) -> None:
        """Reset all analytics state."""
        with self._lock:
            self._requests.clear()
            self._profiles.clear()
            self._counter = 1

    def to_dict(self) -> dict[str, Any]:
        """Serialize analytics state to dictionary.

        Note:
            Calls get_stats(), get_all_profiles(), and get_recent_requests()
            BEFORE acquiring self._lock to prevent deadlock, since
            threading.Lock is not reentrant.

        Returns:
            Dict representation of the full analytics state.
        """
        stats = self.get_stats()
        profiles = self.get_all_profiles()
        recent = self.get_recent_requests(limit=20)
        with self._lock:
            return {
                "max_requests": self._max_requests,
                "request_count": len(self._requests),
                "stats": stats.to_dict(),
                "profiles": [p.to_dict() for p in profiles],
                "recent_requests": [r.to_dict() for r in recent],
            }


# =============================================================================
# Global Instance
# =============================================================================

_instance: EndpointAnalytics | None = None
_lock = threading.Lock()


def get_endpoint_analytics() -> EndpointAnalytics:
    """Get or create the global endpoint analytics singleton.

    Returns:
        The global EndpointAnalytics instance.
    """
    global _instance
    if _instance is None:
        with _lock:
            if _instance is None:
                _instance = EndpointAnalytics()
    return _instance


def reset_endpoint_analytics() -> None:
    """Reset the global endpoint analytics singleton (for testing)."""
    global _instance
    with _lock:
        _instance = None
