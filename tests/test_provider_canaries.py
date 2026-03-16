import asyncio
import json
from pathlib import Path

from core.drivers.protocol import DriverResponse, DriverResponseStatus
from core.drivers.provider_canaries import ProviderCanaryRunner


class _FakeDriver:
    def __init__(self, content: str = "NEXUS_CANARY_OK", healthy: bool = True):
        self.model = "fake-model"
        self._content = content
        self._healthy = healthy

    async def health_check(self) -> bool:
        return self._healthy

    async def invoke(self, prompt: str, **kwargs) -> DriverResponse:  # noqa: ARG002
        return DriverResponse(
            content=self._content,
            status=DriverResponseStatus.SUCCESS,
            provider="fake",
            model=self.model,
            latency_ms=12.5,
            input_tokens=8,
            output_tokens=4,
        )


class _FakeFactory:
    claude_sdk_available = True
    gemini_sdk_available = False
    openai_sdk_available = True
    deepseek_sdk_available = False
    kimi_sdk_available = False
    minimax_sdk_available = False

    def get_claude_sdk(self):
        return _FakeDriver()

    def get_openai_sdk(self):
        return _FakeDriver(content="unexpected")


class _FakeConfig:
    workspace_path = Path("workspace")
    claude_sonnet_model = "claude-sonnet-4-6"
    gemini_pro_model = "gemini-3.1-pro-preview"
    openai_model = "gpt-5.4"
    deepseek_model = "deepseek-chat"
    kimi_model = "kimi-k2-thinking"
    minimax_model = "MiniMax-M2.5"


def test_provider_canary_runner_shapes_results(tmp_path: Path) -> None:
    runner = ProviderCanaryRunner(config=_FakeConfig(), factory=_FakeFactory(), workspace_path=tmp_path)
    report = asyncio.run(runner.run())

    payload = report.to_dict()
    assert payload["summary"]["configured_providers"] == 2
    assert payload["summary"]["attempted_providers"] == 2

    results = {result["provider"]: result for result in payload["results"]}
    assert results["anthropic"]["passed"] is True
    assert results["openai"]["passed"] is False
    assert results["google"]["attempted"] is False


def test_provider_canary_runner_writes_report(tmp_path: Path) -> None:
    runner = ProviderCanaryRunner(config=_FakeConfig(), factory=_FakeFactory(), workspace_path=tmp_path)
    report = asyncio.run(runner.run())
    output_path = tmp_path / "provider-canaries.json"
    asyncio.run(runner.write_report(report, output_path))

    assert output_path.exists()
    payload = json.loads(output_path.read_text(encoding="utf-8"))
    assert payload["results"]
    assert "summary" in payload
