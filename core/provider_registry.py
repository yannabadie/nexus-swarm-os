"""
Provider compatibility registry for runtime, CI, and documentation.

The registry is generated on demand from official provider APIs when possible,
with curated fallbacks for providers that do not expose a stable public model
listing endpoint.
"""

from __future__ import annotations

import json
import os
import re
from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode, urlparse
from urllib.request import Request, urlopen

_REGISTRY_PATH = Path(__file__).with_name("provider_registry.json")
_JSON_HEADERS = {"Accept": "application/json", "Content-Type": "application/json"}
_HTML_HEADERS = {
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "User-Agent": "NEXUS-ProviderRegistry/1.0",
}
_OPENAI_COMPATIBLE_HEADERS = {"Accept": "application/json"}
_DEFAULT_TIMEOUT = 15
_ALLOWED_PROVIDER_HOSTS = frozenset(
    {
        "ai.google.dev",
        "api.anthropic.com",
        "api-docs.deepseek.com",
        "api.deepseek.com",
        "api.minimaxi.com",
        "api.minimaxi.chat",
        "api.moonshot.ai",
        "api.openai.com",
        "developers.openai.com",
        "docs.anthropic.com",
        "platform.moonshot.ai",
        "platform.openai.com",
        "platform.minimaxi.chat",
        "platform.minimaxi.com",
        "www.googleapis.com",
        "generativelanguage.googleapis.com",
    }
)

_SDK_PROVIDER_ATTRS: dict[str, tuple[str, ...]] = {
    "anthropic": ("anthropic_api_key",),
    "google": ("google_api_key",),
    "deepseek": ("deepseek_api_key",),
    "kimi": ("kimi_api_key",),
    "openai": ("openai_api_key",),
    "minimax": ("minimax_api_key",),
}

_DEFAULT_REGISTRY: dict[str, Any] = {
    "schema_version": "2.0",
    "generated_by": "scripts/refresh_provider_registry.py",
    "generated_at": "2026-03-09T00:00:00+00:00",
    "providers": {
        "anthropic": {
            "display_name": "Anthropic",
            "sdk_supported": True,
            "docs_url": "https://docs.anthropic.com/en/docs/about-claude/models/overview",
            "lookup": {"strategy": "docs", "requires_api_key": False},
            "models": {
                "opus": {
                    "default": "claude-opus-4-6",
                    "fallback": "claude-opus-4-6",
                    "status": "active",
                },
                "sonnet": {
                    "default": "claude-sonnet-4-6",
                    "fallback": "claude-sonnet-4-6",
                    "status": "active",
                },
            },
        },
        "google": {
            "display_name": "Google",
            "sdk_supported": True,
            "docs_url": "https://ai.google.dev/gemini-api/docs/models",
            "lookup": {
                "strategy": "api+docs",
                "requires_api_key": False,
                "endpoint": "https://generativelanguage.googleapis.com/v1beta/models",
            },
            "models": {
                "pro": {
                    "default": "gemini-3.1-pro-preview",
                    "fallback": "gemini-2.5-pro",
                    "status": "active",
                },
                "flash": {
                    "default": "gemini-3-flash-preview",
                    "fallback": "gemini-2.5-flash",
                    "status": "active",
                },
            },
        },
        "deepseek": {
            "display_name": "DeepSeek",
            "sdk_supported": True,
            "docs_url": "https://api-docs.deepseek.com/news/news250929",
            "lookup": {
                "strategy": "api+docs",
                "requires_api_key": False,
                "endpoint": "https://api.deepseek.com/models",
            },
            "models": {
                "chat": {
                    "default": "deepseek-chat",
                    "fallback": "deepseek-chat",
                    "status": "active",
                },
                "reasoner": {
                    "default": "deepseek-reasoner",
                    "fallback": "deepseek-reasoner",
                    "status": "active",
                },
            },
        },
        "kimi": {
            "display_name": "Moonshot Kimi",
            "sdk_supported": True,
            "docs_url": "https://platform.moonshot.ai/docs/guide/use-kimi-k2-thinking-model",
            "lookup": {
                "strategy": "api+docs",
                "requires_api_key": False,
                "endpoint": "https://api.moonshot.ai/v1/models",
            },
            "models": {
                "thinking": {
                    "default": "kimi-k2-thinking",
                    "fallback": "kimi-k2-thinking",
                    "status": "active",
                },
                "turbo": {
                    "default": "kimi-k2-thinking-turbo",
                    "fallback": "kimi-k2-thinking-turbo",
                    "status": "preview",
                },
            },
        },
        "openai": {
            "display_name": "OpenAI",
            "sdk_supported": True,
            "docs_url": "https://platform.openai.com/docs/models",
            "lookup": {
                "strategy": "api+docs",
                "requires_api_key": False,
                "endpoint": "https://api.openai.com/v1/models",
            },
            "models": {
                "flagship": {
                    "default": "gpt-5.4",
                    "fallback": "gpt-5.4",
                    "status": "active",
                },
                "balanced": {
                    "default": "gpt-5-mini",
                    "fallback": "gpt-5-mini",
                    "status": "active",
                },
                "economy": {
                    "default": "gpt-5-nano",
                    "fallback": "gpt-5-nano",
                    "status": "active",
                },
            },
        },
        "minimax": {
            "display_name": "MiniMax",
            "sdk_supported": True,
            "docs_url": "https://platform.minimaxi.com/docs/api-reference/text-openai-api",
            "lookup": {
                "strategy": "api+docs",
                "requires_api_key": False,
                "endpoint": "https://api.minimaxi.com/v1/models",
            },
            "models": {
                "reasoning": {
                    "default": "MiniMax-M2.5",
                    "fallback": "MiniMax-M2.5",
                    "status": "active",
                },
                "chat": {
                    "default": "MiniMax-M2.5-HighSpeed",
                    "fallback": "MiniMax-M2.5-HighSpeed",
                    "status": "active",
                },
            },
        },
    },
    "replacements": {
        "claude-opus-4-20250514": "claude-opus-4-6",
        "claude-opus-4-1-20250805": "claude-opus-4-6",
        "claude-opus-4-6-20250116": "claude-opus-4-6",
        "claude-sonnet-4-20250514": "claude-sonnet-4-6",
        "claude-sonnet-4-5-20250929": "claude-sonnet-4-6",
        "gemini-3-pro-preview": "gemini-3.1-pro-preview",
        "gemini-2.5-flash": "gemini-3-flash-preview",
        "gpt-5.2": "gpt-5.4",
        "gpt-5.2-mini": "gpt-5-mini",
        "gpt-5.2-nano": "gpt-5-nano",
        "kimi-k2.5": "kimi-k2-thinking",
        "kimi-k2-turbo-preview": "kimi-k2-thinking-turbo",
        "MiniMax-M1": "MiniMax-M2.5",
    },
}


def load_provider_registry() -> dict[str, Any]:
    """Load the provider compatibility registry from disk."""
    with _REGISTRY_PATH.open(encoding="utf-8") as handle:
        return json.load(handle)


def write_provider_registry(registry: dict[str, Any], output_path: Path | None = None) -> Path:
    """Persist a registry to disk."""
    target = output_path or _REGISTRY_PATH
    target.write_text(json.dumps(registry, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    return target


def get_default_model(provider: str, family: str) -> str:
    """Return the default model configured in the compatibility registry."""
    registry = load_provider_registry()
    return registry["providers"][provider]["models"][family]["default"]


def get_replacement(model_id: str) -> str | None:
    """Return the recommended replacement for a stale model ID."""
    registry = load_provider_registry()
    return registry.get("replacements", {}).get(model_id)


def build_provider_snapshot(config: Any) -> dict[str, Any]:
    """Build a machine-readable snapshot of the runtime provider plan."""
    registry = load_provider_registry()
    selected = {
        "anthropic": {
            "primary_model": getattr(config, "claude_sonnet_model", None),
            "reasoning_model": getattr(config, "claude_opus_model", None),
            "api_key_set": bool(getattr(config, "anthropic_api_key", None)),
        },
        "google": {
            "primary_model": getattr(config, "gemini_pro_model", None),
            "fast_model": getattr(config, "gemini_flash_model", None),
            "api_key_set": bool(getattr(config, "google_api_key", None)),
        },
        "deepseek": {
            "primary_model": getattr(config, "deepseek_model", None),
            "api_key_set": bool(getattr(config, "deepseek_api_key", None)),
        },
        "kimi": {
            "primary_model": getattr(config, "kimi_model", None),
            "api_key_set": bool(getattr(config, "kimi_api_key", None)),
        },
        "openai": {
            "primary_model": getattr(config, "openai_model", None),
            "fast_model": getattr(config, "openai_fast_model", None),
            "api_key_set": bool(getattr(config, "openai_api_key", None)),
        },
        "minimax": {
            "primary_model": getattr(config, "minimax_model", None),
            "fast_model": getattr(config, "minimax_fast_model", None),
            "api_key_set": bool(getattr(config, "minimax_api_key", None)),
        },
    }

    warnings: list[str] = []
    available_sdk_providers: list[str] = []
    driver_mode = getattr(config, "driver_mode", "auto")

    for provider_name, provider_snapshot in selected.items():
        if driver_mode != "cli" and provider_snapshot.get("api_key_set"):
            available_sdk_providers.append(provider_name)
        for field_name, model_id in provider_snapshot.items():
            if field_name == "api_key_set" or not isinstance(model_id, str):
                continue
            replacement = registry.get("replacements", {}).get(model_id)
            if replacement:
                warnings.append(f"{model_id} is stale; use {replacement}")

    return {
        "driver_mode": driver_mode,
        "registry": registry,
        "selected": selected,
        "available_sdk_providers": sorted(available_sdk_providers),
        "warnings": warnings,
    }


def refresh_provider_registry(
    *,
    output_path: Path | None = None,
    timeout: int = _DEFAULT_TIMEOUT,
) -> dict[str, Any]:
    """Refresh the provider registry from official provider APIs when possible."""
    registry = json.loads(json.dumps(_DEFAULT_REGISTRY))
    registry["generated_at"] = datetime.now(UTC).isoformat()
    registry["sync_errors"] = []

    _apply_refresh(registry, "anthropic", lambda: _refresh_anthropic_models(timeout=timeout))
    _apply_refresh(registry, "google", lambda: _refresh_google_models(timeout=timeout))
    _apply_refresh(registry, "openai", lambda: _refresh_openai_models(timeout=timeout))
    _apply_refresh(
        registry,
        "deepseek",
        lambda: _refresh_openai_compatible_models(
            api_key=os.getenv("DEEPSEEK_API_KEY"),
            endpoint="https://api.deepseek.com/models",
            mapping={"chat": "deepseek-chat", "reasoner": "deepseek-reasoner"},
            timeout=timeout,
        ),
    )
    _apply_refresh(
        registry,
        "kimi",
        lambda: _refresh_openai_compatible_models(
            api_key=os.getenv("KIMI_API_KEY"),
            endpoint="https://api.moonshot.ai/v1/models",
            mapping={"thinking": "kimi-k2-thinking", "turbo": "kimi-k2-thinking-turbo"},
            timeout=timeout,
        ),
    )
    _apply_refresh(
        registry,
        "minimax",
        lambda: _refresh_openai_compatible_models(
            api_key=os.getenv("MINIMAX_API_KEY"),
            endpoint="https://api.minimaxi.com/v1/models",
            mapping={"reasoning": "MiniMax-M2.5", "chat": "MiniMax-M2.5-HighSpeed"},
            timeout=timeout,
        ),
    )

    if output_path is not False:
        write_provider_registry(registry, output_path)
    return registry


def _apply_refresh(registry: dict[str, Any], provider: str, callback) -> None:
    try:
        models = callback()
        if models:
            registry["providers"][provider]["models"] = models
    except Exception as exc:
        registry.setdefault("sync_errors", []).append(f"{provider}: {exc}")


def _refresh_google_models(*, timeout: int) -> dict[str, Any] | None:
    api_key = os.getenv("GOOGLE_API_KEY") or os.getenv("GEMINI_API_KEY")
    if not api_key:
        return _refresh_google_models_from_docs(timeout=timeout)

    params = urlencode({"key": api_key})
    data = _fetch_json(f"https://generativelanguage.googleapis.com/v1beta/models?{params}", timeout=timeout)
    model_ids = [
        item.get("name", "").split("/", 1)[-1]
        for item in data.get("models", [])
        if isinstance(item, dict) and item.get("name")
    ]
    pro = _pick_best_model(model_ids, [r"^gemini-3(?:\.\d+)?-pro(?:-preview)?$", r"^gemini-2\.5-pro$"])
    flash = _pick_best_model(model_ids, [r"^gemini-3(?:\.\d+)?-flash(?:-preview)?$", r"^gemini-2\.5-flash$"])
    if not pro and not flash:
        return None
    current = _DEFAULT_REGISTRY["providers"]["google"]["models"]
    return {
        "pro": {
            "default": pro or current["pro"]["default"],
            "fallback": current["pro"]["fallback"],
            "status": "active",
        },
        "flash": {
            "default": flash or current["flash"]["default"],
            "fallback": current["flash"]["fallback"],
            "status": "active",
        },
    }


def _refresh_openai_models(*, timeout: int) -> dict[str, Any] | None:
    api_key = os.getenv("OPENAI_API_KEY")
    if not api_key:
        return _refresh_openai_models_from_docs(timeout=timeout)

    data = _fetch_json(
        "https://api.openai.com/v1/models",
        timeout=timeout,
        headers={"Authorization": f"Bearer {api_key}", **_OPENAI_COMPATIBLE_HEADERS},
    )
    model_ids = [item.get("id", "") for item in data.get("data", []) if isinstance(item, dict) and item.get("id")]
    flagship = _pick_best_model(model_ids, [r"^gpt-(\d+(?:\.\d+)*)$"])
    balanced = _pick_best_model(model_ids, [r"^gpt-(\d+(?:\.\d+)*)-mini$"])
    economy = _pick_best_model(model_ids, [r"^gpt-(\d+(?:\.\d+)*)-nano$"])
    if not flagship and not balanced and not economy:
        return None
    current = _DEFAULT_REGISTRY["providers"]["openai"]["models"]
    return {
        "flagship": {
            "default": flagship or current["flagship"]["default"],
            "fallback": current["flagship"]["fallback"],
            "status": "active",
        },
        "balanced": {
            "default": balanced or current["balanced"]["default"],
            "fallback": current["balanced"]["fallback"],
            "status": "active",
        },
        "economy": {
            "default": economy or current["economy"]["default"],
            "fallback": current["economy"]["fallback"],
            "status": "active",
        },
    }


def _refresh_openai_compatible_models(
    *,
    api_key: str | None,
    endpoint: str,
    mapping: dict[str, str],
    timeout: int,
) -> dict[str, Any] | None:
    if not api_key:
        return _refresh_openai_compatible_models_from_docs(mapping=mapping, endpoint=endpoint, timeout=timeout)

    data = _fetch_json(
        endpoint,
        timeout=timeout,
        headers={"Authorization": f"Bearer {api_key}", **_OPENAI_COMPATIBLE_HEADERS},
    )
    model_ids = {item.get("id", "") for item in data.get("data", []) if isinstance(item, dict) and item.get("id")}
    refreshed: dict[str, Any] = {}
    for family, preferred_id in mapping.items():
        chosen = preferred_id if preferred_id in model_ids else _pick_same_prefix(model_ids, preferred_id)
        refreshed[family] = {
            "default": chosen or preferred_id,
            "fallback": preferred_id,
            "status": "active",
        }
    return refreshed


def _pick_best_model(model_ids: list[str], patterns: list[str]) -> str | None:
    matches: list[str] = []
    for pattern in patterns:
        regex = re.compile(pattern, re.IGNORECASE)
        matches.extend(model_id for model_id in model_ids if regex.match(model_id))
        if matches:
            break
    if not matches:
        return None
    return sorted(set(matches), key=_version_sort_key, reverse=True)[0]


def _pick_same_prefix(model_ids: set[str], preferred_id: str) -> str | None:
    prefix = re.split(r"[-_](?:thinking|turbo|preview|mini|nano|\d)", preferred_id, maxsplit=1)[0]
    candidates = [model_id for model_id in model_ids if model_id.startswith(prefix)]
    if not candidates:
        return None
    return sorted(set(candidates), key=_version_sort_key, reverse=True)[0]


def _version_sort_key(model_id: str) -> tuple[Any, ...]:
    parts: list[Any] = []
    for token in re.split(r"([0-9]+(?:\.[0-9]+)*)", model_id):
        if not token:
            continue
        if re.fullmatch(r"[0-9]+(?:\.[0-9]+)*", token):
            parts.extend(int(part) for part in token.split("."))
        else:
            parts.append(token.lower())
    return tuple(parts)


def _validate_registry_url(url: str) -> None:
    parsed = urlparse(url)
    if parsed.scheme != "https":
        raise RuntimeError(f"Provider registry refresh only allows HTTPS URLs: {url}")
    if not parsed.hostname or parsed.hostname not in _ALLOWED_PROVIDER_HOSTS:
        raise RuntimeError(f"Provider registry refresh host is not allowlisted: {url}")


def _fetch_json(url: str, *, timeout: int, headers: dict[str, str] | None = None) -> dict[str, Any]:
    _validate_registry_url(url)
    request_headers = dict(_JSON_HEADERS)
    if headers:
        request_headers.update(headers)
    request = Request(url, headers=request_headers, method="GET")
    try:
        # Official provider endpoint on an explicit HTTPS allowlist.
        with urlopen(request, timeout=timeout) as response:  # nosec B310
            return json.loads(response.read().decode("utf-8"))
    except HTTPError as exc:
        raise RuntimeError(f"{url} returned HTTP {exc.code}") from exc
    except URLError as exc:
        raise RuntimeError(f"Failed to reach {url}: {exc.reason}") from exc


def _fetch_text(url: str, *, timeout: int) -> str:
    _validate_registry_url(url)
    request = Request(url, headers=_HTML_HEADERS, method="GET")
    try:
        # Official provider endpoint on an explicit HTTPS allowlist.
        with urlopen(request, timeout=timeout) as response:  # nosec B310
            return response.read().decode("utf-8", errors="replace")
    except HTTPError as exc:
        raise RuntimeError(f"{url} returned HTTP {exc.code}") from exc
    except URLError as exc:
        raise RuntimeError(f"Failed to reach {url}: {exc.reason}") from exc


def _refresh_anthropic_models(*, timeout: int) -> dict[str, Any] | None:
    text = _fetch_text(_DEFAULT_REGISTRY["providers"]["anthropic"]["docs_url"], timeout=timeout).lower()
    current = _DEFAULT_REGISTRY["providers"]["anthropic"]["models"]
    opus = "claude-opus-4-6" if "claude-opus-4-6" in text or "opus 4.6" in text else current["opus"]["default"]
    sonnet = (
        "claude-sonnet-4-6" if "claude-sonnet-4-6" in text or "sonnet 4.6" in text else current["sonnet"]["default"]
    )
    return {
        "opus": {"default": opus, "fallback": current["opus"]["fallback"], "status": "active"},
        "sonnet": {"default": sonnet, "fallback": current["sonnet"]["fallback"], "status": "active"},
    }


def _refresh_google_models_from_docs(*, timeout: int) -> dict[str, Any] | None:
    text = " ".join(
        [
            _fetch_text("https://ai.google.dev/gemini-api/docs/deprecations", timeout=timeout).lower(),
            _fetch_text(_DEFAULT_REGISTRY["providers"]["google"]["docs_url"], timeout=timeout).lower(),
        ]
    )
    current = _DEFAULT_REGISTRY["providers"]["google"]["models"]
    pro = "gemini-3.1-pro-preview" if "gemini-3.1-pro-preview" in text else current["pro"]["default"]
    flash = current["flash"]["default"]
    if "gemini-3-flash-preview" in text:
        flash = "gemini-3-flash-preview"
    elif "gemini-3.1-flash-preview" in text:
        flash = "gemini-3.1-flash-preview"
    return {
        "pro": {"default": pro, "fallback": current["pro"]["fallback"], "status": "active"},
        "flash": {"default": flash, "fallback": current["flash"]["fallback"], "status": "active"},
    }


def _refresh_openai_models_from_docs(*, timeout: int) -> dict[str, Any] | None:
    text = _fetch_text(_DEFAULT_REGISTRY["providers"]["openai"]["docs_url"], timeout=timeout).lower()
    current = _DEFAULT_REGISTRY["providers"]["openai"]["models"]
    flagship = "gpt-5.4" if "gpt-5.4" in text else current["flagship"]["default"]
    balanced = "gpt-5-mini" if "gpt-5 mini" in text or "gpt-5-mini" in text else current["balanced"]["default"]
    economy = "gpt-5-nano" if "gpt-5 nano" in text or "gpt-5-nano" in text else current["economy"]["default"]
    return {
        "flagship": {"default": flagship, "fallback": current["flagship"]["fallback"], "status": "active"},
        "balanced": {"default": balanced, "fallback": current["balanced"]["fallback"], "status": "active"},
        "economy": {"default": economy, "fallback": current["economy"]["fallback"], "status": "active"},
    }


def _refresh_openai_compatible_models_from_docs(
    *,
    mapping: dict[str, str],
    endpoint: str,
    timeout: int,
) -> dict[str, Any] | None:
    docs_url = next(
        (
            provider_data["docs_url"]
            for provider_data in _DEFAULT_REGISTRY["providers"].values()
            if provider_data.get("lookup", {}).get("endpoint") == endpoint
        ),
        None,
    )
    if not docs_url:
        return None
    text = _fetch_text(docs_url, timeout=timeout).lower()
    refreshed: dict[str, Any] = {}
    for family, preferred_id in mapping.items():
        candidates = [preferred_id]
        if preferred_id == "kimi-k2-thinking-turbo":
            candidates.append("kimi-k2-turbo-preview")
        if preferred_id == "MiniMax-M2.5":
            candidates.append("MiniMax-M1")
        chosen = next((candidate for candidate in candidates if candidate.lower() in text), preferred_id)
        refreshed[family] = {"default": chosen, "fallback": preferred_id, "status": "active"}
    return refreshed


__all__ = [
    "build_provider_snapshot",
    "get_default_model",
    "get_replacement",
    "load_provider_registry",
    "refresh_provider_registry",
    "write_provider_registry",
]
