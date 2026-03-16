from __future__ import annotations

from pathlib import Path

from core.provider_registry import build_provider_snapshot, load_provider_registry, refresh_provider_registry


def test_provider_registry_exposes_all_sdk_providers():
    registry = load_provider_registry()

    assert registry["schema_version"] == "2.0"
    assert set(registry["providers"]) >= {"anthropic", "google", "deepseek", "kimi", "openai", "minimax"}


def test_build_provider_snapshot_includes_auxiliary_sdk_providers():
    class StubConfig:
        driver_mode = "sdk"
        anthropic_api_key = "sk-ant"
        google_api_key = "sk-goog"
        deepseek_api_key = "sk-deepseek"
        kimi_api_key = None
        openai_api_key = "sk-openai"
        minimax_api_key = "sk-minimax"
        claude_sonnet_model = "claude-sonnet-4-6"
        claude_opus_model = "claude-opus-4-6"
        gemini_pro_model = "gemini-3.1-pro-preview"
        gemini_flash_model = "gemini-3-flash-preview"
        deepseek_model = "deepseek-chat"
        kimi_model = "kimi-k2-thinking"
        openai_model = "gpt-5.4"
        openai_fast_model = "gpt-5-mini"
        minimax_model = "MiniMax-M2.5"
        minimax_fast_model = "MiniMax-M2.5-HighSpeed"

    snapshot = build_provider_snapshot(StubConfig())

    assert snapshot["driver_mode"] == "sdk"
    assert set(snapshot["available_sdk_providers"]) == {"anthropic", "google", "deepseek", "openai", "minimax"}
    assert snapshot["selected"]["openai"]["primary_model"] == "gpt-5.4"
    assert snapshot["selected"]["minimax"]["fast_model"] == "MiniMax-M2.5-HighSpeed"


def test_refresh_provider_registry_uses_provider_api_results(monkeypatch):
    monkeypatch.setenv("OPENAI_API_KEY", "sk-openai")

    def fake_fetch_json(url: str, *, timeout: int, headers=None):
        assert timeout == 3
        if "openai.com" in url:
            return {
                "data": [
                    {"id": "gpt-5.4"},
                    {"id": "gpt-5-mini"},
                    {"id": "gpt-5-nano"},
                ]
            }
        raise AssertionError(f"Unexpected URL: {url}")

    monkeypatch.setattr("core.provider_registry._fetch_json", fake_fetch_json)
    registry = refresh_provider_registry(output_path=False, timeout=3)

    assert registry["providers"]["openai"]["models"]["flagship"]["default"] == "gpt-5.4"
    assert registry["providers"]["openai"]["models"]["balanced"]["default"] == "gpt-5-mini"
    assert registry["providers"]["openai"]["models"]["economy"]["default"] == "gpt-5-nano"


def test_refresh_provider_registry_writes_output(monkeypatch, tmp_path: Path):
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    output = tmp_path / "provider_registry.json"

    registry = refresh_provider_registry(output_path=output)

    assert output.exists()
    assert registry["providers"]["minimax"]["models"]["reasoning"]["default"] == "MiniMax-M2.5"
