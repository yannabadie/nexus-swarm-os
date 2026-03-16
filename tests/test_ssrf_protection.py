"""
Test SSRF Protection for web_fetch handler.

NEXUS V12.4 Security - Comprehensive SSRF blocklist tests.
"""

from pathlib import Path

import pytest

from core.execution_pkg.execution.handlers.web_handlers import WebFetchHandler


@pytest.fixture
def handler(tmp_path: Path) -> WebFetchHandler:
    """Create handler for testing."""
    return WebFetchHandler(tmp_path, None)


class TestSSRFBlockedHosts:
    """Test hostname-based SSRF blocking."""

    @pytest.mark.parametrize(
        "hostname",
        [
            "localhost",
            "localhost.localdomain",
            "localhost6",
            "metadata.google.internal",
            "metadata.google",
            "kubernetes.default",
            "kubernetes.default.svc.cluster.local",
        ],
    )
    def test_blocked_hostnames(self, handler: WebFetchHandler, hostname: str):
        """Blocked hostnames should be rejected."""
        url = f"http://{hostname}/some/path"
        is_blocked, reason = handler._is_ssrf_target(url)
        assert is_blocked, f"{hostname} should be blocked"
        assert "Blocked hostname" in reason

    @pytest.mark.parametrize(
        "hostname",
        [
            "example.internal",
            "app.local",
            "test.localhost",
        ],
    )
    def test_blocked_hostname_patterns(self, handler: WebFetchHandler, hostname: str):
        """Blocked hostname patterns should be rejected."""
        url = f"http://{hostname}/api"
        is_blocked, reason = handler._is_ssrf_target(url)
        assert is_blocked, f"{hostname} should be blocked by pattern"


class TestSSRFBlockedIPs:
    """Test IP-based SSRF blocking."""

    @pytest.mark.parametrize(
        "ip",
        [
            "127.0.0.1",
            "127.0.0.2",
            "127.1.1.1",
        ],
    )
    def test_loopback_ips(self, handler: WebFetchHandler, ip: str):
        """Loopback IPs should be blocked."""
        url = f"http://{ip}/api"
        is_blocked, reason = handler._is_ssrf_target(url)
        assert is_blocked, f"{ip} should be blocked"
        assert "Loopback" in reason or "Private" in reason

    @pytest.mark.parametrize(
        "ip",
        [
            "10.0.0.1",
            "10.255.255.255",
            "172.16.0.1",
            "172.31.255.255",
            "192.168.0.1",
            "192.168.255.255",
        ],
    )
    def test_private_ips(self, handler: WebFetchHandler, ip: str):
        """Private IPs should be blocked."""
        url = f"http://{ip}/internal"
        is_blocked, reason = handler._is_ssrf_target(url)
        assert is_blocked, f"{ip} should be blocked"
        assert "Private" in reason

    @pytest.mark.parametrize(
        "ip",
        [
            "169.254.169.254",  # AWS/Cloud metadata
            "169.254.0.1",  # Link-local
            "169.254.255.255",  # Link-local
        ],
    )
    def test_link_local_and_metadata(self, handler: WebFetchHandler, ip: str):
        """Link-local and metadata IPs should be blocked."""
        url = f"http://{ip}/latest/meta-data"
        is_blocked, reason = handler._is_ssrf_target(url)
        assert is_blocked, f"{ip} should be blocked"

    @pytest.mark.parametrize(
        "ip",
        [
            "0.0.0.0",
            "[::]",
            "[::1]",
        ],
    )
    def test_special_blocked_ips(self, handler: WebFetchHandler, ip: str):
        """Special IPs should be blocked."""
        url = f"http://{ip}/"
        is_blocked, reason = handler._is_ssrf_target(url)
        assert is_blocked, f"{ip} should be blocked"


class TestSSRFBypassPrevention:
    """Test bypass attempt prevention."""

    @pytest.mark.parametrize(
        "bypass_ip",
        [
            "0x7f000001",  # Hex: 127.0.0.1
            "2130706433",  # Decimal: 127.0.0.1
            "017700000001",  # Octal-like
        ],
    )
    def test_ip_encoding_bypasses(self, handler: WebFetchHandler, bypass_ip: str):
        """Encoded IP bypasses should be blocked."""
        url = f"http://{bypass_ip}/"
        is_blocked, reason = handler._is_ssrf_target(url)
        assert is_blocked, f"{bypass_ip} bypass should be blocked"


class TestSSRFAllowedUrls:
    """Test that legitimate URLs are allowed."""

    @pytest.mark.parametrize(
        "url",
        [
            "https://www.google.com/search",
            "https://api.github.com/repos",
            "https://docs.python.org/3/",
            "https://example.com:443/api",
            "http://example.com:8080/api",
        ],
    )
    def test_public_urls_allowed(self, handler: WebFetchHandler, url: str):
        """Public URLs should be allowed."""
        is_blocked, reason = handler._is_ssrf_target(url)
        assert not is_blocked, f"{url} should be allowed, but got: {reason}"


class TestSSRFExecuteIntegration:
    """Test execute() method with SSRF protection."""

    def test_ssrf_blocked_returns_error(self, handler: WebFetchHandler):
        """Blocked URL should return error ToolResult."""
        result = handler.execute({"url": "http://localhost/admin"})
        assert result.status == "ERROR"
        assert "SSRF Protection" in result.error

    def test_ssrf_metadata_blocked(self, handler: WebFetchHandler):
        """AWS metadata endpoint should be blocked."""
        result = handler.execute({"url": "http://169.254.169.254/latest/meta-data"})
        assert result.status == "ERROR"
        assert "SSRF" in result.error

    def test_ssrf_internal_blocked(self, handler: WebFetchHandler):
        """Internal hostname should be blocked."""
        result = handler.execute({"url": "http://app.internal/api"})
        assert result.status == "ERROR"
        assert "SSRF" in result.error


class TestSSRFPortBlocking:
    """Test port-based restrictions."""

    def test_low_port_blocked(self, handler: WebFetchHandler):
        """Low ports (except 80/443) should be blocked."""
        url = "http://example.com:22/ssh"
        is_blocked, reason = handler._is_ssrf_target(url)
        assert is_blocked, "Port 22 should be blocked"
        assert "port" in reason.lower()

    @pytest.mark.parametrize("port", [80, 443, 8080, 8443])
    def test_common_ports_allowed(self, handler: WebFetchHandler, port: int):
        """Common web ports should be allowed."""
        url = f"http://example.com:{port}/api"
        is_blocked, reason = handler._is_ssrf_target(url)
        assert not is_blocked, f"Port {port} should be allowed"
