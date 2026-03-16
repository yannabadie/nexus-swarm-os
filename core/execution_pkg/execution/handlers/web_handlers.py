"""
Web Handlers - Web search and fetch operations.

NEXUS V9.6 Sprint 5.2b - Extracted from tool_manager.py
NEXUS V12.4 Security - SSRF Protection

Provides:
- WebSearchHandler: Search via Gemini CLI grounding
- WebFetchHandler: Fetch URL content with SSRF protection
"""

from __future__ import annotations

import ipaddress
import re
import socket
import subprocess  # nosec B404
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

from .base import BaseHandler, ToolResult

# =============================================================================
# V12.4 SSRF PROTECTION - Comprehensive Blocklist
# =============================================================================
# Based on OWASP SSRF Prevention Cheat Sheet, PayloadsAllTheThings, HackTricks
# https://cheatsheetseries.owasp.org/cheatsheets/Server_Side_Request_Forgery_Prevention_Cheat_Sheet.html

# Blocked hostnames (exact match, case-insensitive)
SSRF_BLOCKED_HOSTS = frozenset(
    [
        # Localhost variants
        "localhost",
        "localhost.localdomain",
        "localhost6",
        "localhost6.localdomain6",
        # Cloud metadata hostnames
        "metadata.google.internal",
        "metadata.google",
        "metadata",
        # Kubernetes
        "kubernetes.default",
        "kubernetes.default.svc",
        "kubernetes.default.svc.cluster.local",
    ]
)

# Blocked hostname patterns (regex)
SSRF_BLOCKED_HOST_PATTERNS = [
    re.compile(r"^.*\.internal$", re.IGNORECASE),  # *.internal
    re.compile(r"^.*\.local$", re.IGNORECASE),  # *.local
    re.compile(r"^.*\.localhost$", re.IGNORECASE),  # *.localhost
    re.compile(r"^169\.254\.\d+\.\d+$"),  # Link-local IP as hostname
    re.compile(r"^0x[0-9a-f]+$", re.IGNORECASE),  # Hex IP (0x7f000001)
    re.compile(r"^\d{8,10}$"),  # Decimal IP (2130706433)
    re.compile(r"^0+\d"),  # Octal IP (0177.0.0.1)
]

# Private/Reserved IP ranges (will be checked via ipaddress module)
# - 10.0.0.0/8       (Private Class A)
# - 172.16.0.0/12    (Private Class B)
# - 192.168.0.0/16   (Private Class C)
# - 127.0.0.0/8      (Loopback)
# - 169.254.0.0/16   (Link-local)
# - ::1/128          (IPv6 loopback)
# - fc00::/7         (IPv6 unique local)
# - fe80::/10        (IPv6 link-local)
# - fd00:ec2::254    (AWS EC2 IPv6 metadata)

# Special IPs to block explicitly (bypass attempts)
SSRF_BLOCKED_IPS = frozenset(
    [
        # Blocked SSRF target, not a bind address.
        "0.0.0.0",  # nosec B104
        "0",
        "[::]",
        "[::1]",
        "[0:0:0:0:0:0:0:0]",
        "[0:0:0:0:0:0:0:1]",
        "fd00:ec2::254",  # AWS IPv6 metadata
    ]
)


class WebSearchHandler(BaseHandler):
    """
    Handler for web search via Gemini CLI.

    Uses Gemini CLI's google_web_search tool for grounding.
    """

    @property
    def tool_name(self) -> str:
        return "web_search"

    def execute(self, args: dict[str, Any]) -> ToolResult:
        """
        Execute web search via Gemini CLI.

        Args:
            args: {
                "query": "search query string",
                "num_results": 5 (optional, default: 5)
            }

        Returns:
            ToolResult with search results
        """
        query = args.get("query", "")
        num_results = args.get("num_results", 5)

        if not query:
            return self._error("Query parameter is required")

        try:
            # Use Gemini CLI for web search with grounding
            command = [
                "gemini",
                "-m",
                "gemini-3-pro-preview",
                "-p",
                f"You have access to Google Search. Search for: '{query}'. "
                f"Provide a detailed summary of the top {num_results} results including titles and URLs.",
            ]

            # Controlled Gemini CLI invocation, validated command construction.
            result = subprocess.run(  # nosec B603
                command,
                capture_output=True,
                text=True,
                timeout=90,  # Increased for grounding latency
                encoding="utf-8",
                errors="replace",
            )

            if result.returncode == 0:
                return ToolResult(
                    tool_name=self.tool_name,
                    status="SUCCESS",
                    output=result.stdout or "(no results)",
                    error=result.stderr,
                )
            else:
                error_msg = f"Stderr: {result.stderr}\nStdout: {result.stdout}"
                return ToolResult(tool_name=self.tool_name, status="FAILURE", output=result.stdout, error=error_msg)

        except subprocess.TimeoutExpired:
            return self._error("Web search timed out after 90s")
        except FileNotFoundError:
            return self._error("Gemini CLI not found. Web search requires Gemini CLI.")
        except Exception as e:
            return self._error(f"Web search error: {str(e)}")


class WebFetchHandler(BaseHandler):
    """
    Handler for fetching URL content.

    Fetches web content with proper encoding handling.
    V12.4: Includes comprehensive SSRF protection.
    """

    # Default user agent to avoid 403 blocks
    USER_AGENT = (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/120.0.0.0 Safari/537.36"
    )

    @property
    def tool_name(self) -> str:
        return "web_fetch"

    def _is_ssrf_target(self, url: str) -> tuple[bool, str]:
        """
        V12.4 Security: Check if URL targets internal/metadata endpoints.

        Returns:
            (is_blocked, reason) - True if URL should be blocked
        """
        try:
            parsed = urlparse(url)
            hostname = parsed.hostname or ""
            port = parsed.port

            # 1. Check blocked hostnames (exact match)
            if hostname.lower() in SSRF_BLOCKED_HOSTS:
                return True, f"Blocked hostname: {hostname}"

            # 2. Check blocked hostname patterns
            for pattern in SSRF_BLOCKED_HOST_PATTERNS:
                if pattern.match(hostname):
                    return True, f"Blocked hostname pattern: {hostname}"

            # 3. Check explicit blocked IPs
            if hostname in SSRF_BLOCKED_IPS:
                return True, f"Blocked IP: {hostname}"

            # 4. Resolve hostname and check IP
            try:
                # Get all resolved IPs
                infos = socket.getaddrinfo(hostname, port or 80, socket.AF_UNSPEC)
                for info in infos:
                    ip_str = info[4][0]
                    try:
                        ip = ipaddress.ip_address(ip_str)

                        # Check if private/reserved
                        if ip.is_private:
                            return True, f"Private IP: {ip_str}"
                        if ip.is_loopback:
                            return True, f"Loopback IP: {ip_str}"
                        if ip.is_link_local:
                            return True, f"Link-local IP: {ip_str}"
                        if ip.is_reserved:
                            return True, f"Reserved IP: {ip_str}"
                        if ip.is_multicast:
                            return True, f"Multicast IP: {ip_str}"

                        # AWS metadata IP (169.254.169.254)
                        if ip_str == "169.254.169.254":
                            return True, "AWS/Cloud metadata endpoint"

                    except ValueError:
                        # Not a valid IP, skip
                        pass
            except socket.gaierror:
                # DNS resolution failed - allow (will fail later with URLError)
                pass

            # 5. Block suspicious ports
            if port and port in (80, 443, 8080, 8443, 9001):
                # Common ports are allowed
                pass
            elif port and port < 1024 and port not in (80, 443):
                # Block low ports except HTTP/HTTPS
                return True, f"Blocked low port: {port}"

            return False, ""

        except Exception as e:
            # On any parsing error, block to be safe
            return True, f"URL parsing error: {e}"

    def execute(self, args: dict[str, Any]) -> ToolResult:
        """
        Fetch content from a URL.

        Args:
            args: {
                "url": "https://example.com",
                "max_length": 10000 (optional, default: 10000 chars)
            }

        Returns:
            ToolResult with URL content

        Examples:
            {"url": "https://docs.python.org/3/library/asyncio.html"}
            {"url": "https://api.github.com/repos/python/cpython", "max_length": 5000}
        """
        url = args.get("url", "")
        max_length = args.get("max_length", 10000)

        if not url:
            return self._error("URL parameter is required")

        # Basic URL validation
        if not url.startswith(("http://", "https://")):
            return self._error("URL must start with http:// or https://")

        # V12.4 Security: SSRF Protection
        is_blocked, reason = self._is_ssrf_target(url)
        if is_blocked:
            return self._error(f"SSRF Protection: {reason}")

        try:
            # Create request with browser user agent
            req = urllib.request.Request(url, headers={"User-Agent": self.USER_AGENT})

            # Fetch URL
            # URL was SSRF-validated and resolved before fetch.
            with urllib.request.urlopen(req, timeout=30) as response:  # nosec B310
                content_type = response.headers.get("Content-Type", "")

                # Read content
                content_bytes = response.read()

                # Decode based on content type
                encoding = self._extract_encoding(content_type)
                content = self._decode_content(content_bytes, encoding)

                # Truncate if too long
                if len(content) > max_length:
                    content = content[:max_length] + f"\n\n[Content truncated at {max_length} characters]"

                return ToolResult(
                    tool_name=self.tool_name,
                    status="SUCCESS",
                    output=f"URL: {url}\nContent-Type: {content_type}\n\n{content}",
                )

        except urllib.error.HTTPError as e:
            return self._fail(f"HTTP Error {e.code}: {e.reason}")
        except urllib.error.URLError as e:
            return self._error(f"URL Error: {e.reason}")
        except Exception as e:
            return self._error(f"Web fetch error: {str(e)}")

    def _extract_encoding(self, content_type: str) -> str:
        """Extract encoding from Content-Type header."""
        if "charset=" in content_type:
            return content_type.split("charset=")[1].split(";")[0].strip()
        return "utf-8"

    def _decode_content(self, content_bytes: bytes, encoding: str) -> str:
        """Decode bytes with fallback to UTF-8."""
        try:
            return content_bytes.decode(encoding, errors="replace")
        except Exception:
            return content_bytes.decode("utf-8", errors="replace")


def create_web_handlers(workspace_path: Path, validation_service: Any = None) -> dict[str, BaseHandler]:
    """
    Factory function to create web handlers.

    Args:
        workspace_path: Workspace root path
        validation_service: Optional validation service

    Returns:
        Dict mapping tool names to handlers
    """
    return {
        "web_search": WebSearchHandler(workspace_path, validation_service),
        "web_fetch": WebFetchHandler(workspace_path, validation_service),
    }
