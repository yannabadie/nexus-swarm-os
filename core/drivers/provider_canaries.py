"""
Live provider canary runner for NEXUS.

Runs a tiny fixed task suite against configured SDK providers and exports
machine-readable evidence. This is intentionally separate from structural
smoke jobs so routine CI can distinguish wiring from live execution.
"""

from __future__ import annotations

import asyncio
import json
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from core.config import Config

from .async_factory import AsyncDriverFactory, create_driver_factory
from .protocol import DriverResponseStatus

CANARY_PROMPT = "Reply with exactly NEXUS_CANARY_OK and nothing else."
CANARY_EXPECTED = "NEXUS_CANARY_OK"

PROVIDER_SPECS = {
    "anthropic": {
        "availability_attr": "claude_sdk_available",
        "factory_method": "get_claude_sdk",
        "model_attr": "claude_sonnet_model",
    },
    "google": {
        "availability_attr": "gemini_sdk_available",
        "factory_method": "get_gemini_sdk",
        "model_attr": "gemini_pro_model",
    },
    "openai": {
        "availability_attr": "openai_sdk_available",
        "factory_method": "get_openai_sdk",
        "model_attr": "openai_model",
    },
    "deepseek": {
        "availability_attr": "deepseek_sdk_available",
        "factory_method": "get_deepseek_sdk",
        "model_attr": "deepseek_model",
    },
    "kimi": {
        "availability_attr": "kimi_sdk_available",
        "factory_method": "get_kimi_sdk",
        "model_attr": "kimi_model",
    },
    "minimax": {
        "availability_attr": "minimax_sdk_available",
        "factory_method": "get_minimax_sdk",
        "model_attr": "minimax_model",
    },
}


@dataclass
class ProviderCanaryResult:
    provider: str
    configured: bool
    attempted: bool
    passed: bool
    model: str | None = None
    health_check_passed: bool | None = None
    response_status: str | None = None
    output_preview: str = ""
    latency_ms: float = 0.0
    input_tokens: int = 0
    output_tokens: int = 0
    error: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "provider": self.provider,
            "configured": self.configured,
            "attempted": self.attempted,
            "passed": self.passed,
            "model": self.model,
            "health_check_passed": self.health_check_passed,
            "response_status": self.response_status,
            "output_preview": self.output_preview,
            "latency_ms": round(self.latency_ms, 2),
            "input_tokens": self.input_tokens,
            "output_tokens": self.output_tokens,
            "error": self.error,
        }


@dataclass
class ProviderCanaryReport:
    generated_at: str
    prompt: str
    expected: str
    results: list[ProviderCanaryResult] = field(default_factory=list)

    def summary(self) -> dict[str, Any]:
        configured = [result for result in self.results if result.configured]
        attempted = [result for result in self.results if result.attempted]
        passed = [result for result in attempted if result.passed]
        failed = [result for result in attempted if not result.passed]
        skipped = [result for result in self.results if not result.attempted]
        return {
            "configured_providers": len(configured),
            "attempted_providers": len(attempted),
            "passed_providers": len(passed),
            "failed_providers": len(failed),
            "skipped_providers": len(skipped),
            "pass_rate": (len(passed) / len(attempted)) if attempted else 0.0,
        }

    def to_dict(self) -> dict[str, Any]:
        return {
            "generated_at": self.generated_at,
            "prompt": self.prompt,
            "expected": self.expected,
            "summary": self.summary(),
            "results": [result.to_dict() for result in self.results],
        }


class ProviderCanaryRunner:
    """Run fixed-task live canaries against configured SDK providers."""

    def __init__(
        self,
        config: Config | None = None,
        factory: AsyncDriverFactory | None = None,
        workspace_path: Path | None = None,
    ) -> None:
        self.config = config or Config()
        self.workspace_path = Path(workspace_path or self.config.workspace_path)
        self.factory = factory or create_driver_factory(self.config, self.workspace_path)

    async def run(self) -> ProviderCanaryReport:
        results: list[ProviderCanaryResult] = []
        for provider_name, spec in PROVIDER_SPECS.items():
            results.append(await self._run_provider(provider_name, spec))
        return ProviderCanaryReport(
            generated_at=datetime.now(UTC).isoformat(),
            prompt=CANARY_PROMPT,
            expected=CANARY_EXPECTED,
            results=results,
        )

    async def write_report(self, report: ProviderCanaryReport, output_path: Path) -> Path:
        output_path.parent.mkdir(parents=True, exist_ok=True)
        output_path.write_text(json.dumps(report.to_dict(), indent=2, ensure_ascii=True) + "\n", encoding="utf-8")
        return output_path

    async def _run_provider(self, provider_name: str, spec: dict[str, str]) -> ProviderCanaryResult:
        configured = bool(getattr(self.factory, spec["availability_attr"], False))
        model = getattr(self.config, spec["model_attr"], None)

        if not configured:
            return ProviderCanaryResult(
                provider=provider_name,
                configured=False,
                attempted=False,
                passed=False,
                model=model,
                error="Provider SDK not configured in this environment.",
            )

        try:
            driver = getattr(self.factory, spec["factory_method"])()
        except Exception as exc:
            return ProviderCanaryResult(
                provider=provider_name,
                configured=True,
                attempted=False,
                passed=False,
                model=model,
                error=f"Driver initialization failed: {exc}",
            )

        health_ok = None
        try:
            health_ok = await driver.health_check()
        except Exception as exc:
            return ProviderCanaryResult(
                provider=provider_name,
                configured=True,
                attempted=True,
                passed=False,
                model=getattr(driver, "model", model),
                health_check_passed=False,
                error=f"Health check failed: {exc}",
            )

        try:
            response = await driver.invoke(CANARY_PROMPT, temperature=0.0, max_tokens=32)
        except Exception as exc:
            return ProviderCanaryResult(
                provider=provider_name,
                configured=True,
                attempted=True,
                passed=False,
                model=getattr(driver, "model", model),
                health_check_passed=health_ok,
                error=f"Canary invocation failed: {exc}",
            )

        content = (response.content or "").strip()
        passed = (
            response.status == DriverResponseStatus.SUCCESS
            and health_ok is True
            and CANARY_EXPECTED in content
        )
        return ProviderCanaryResult(
            provider=provider_name,
            configured=True,
            attempted=True,
            passed=passed,
            model=getattr(driver, "model", model),
            health_check_passed=health_ok,
            response_status=response.status.name,
            output_preview=content[:120],
            latency_ms=response.latency_ms,
            input_tokens=response.input_tokens,
            output_tokens=response.output_tokens,
            error=None if passed else response.error_message or f"Unexpected output: {content[:120]}",
        )


__all__ = [
    "CANARY_EXPECTED",
    "CANARY_PROMPT",
    "PROVIDER_SPECS",
    "ProviderCanaryReport",
    "ProviderCanaryResult",
    "ProviderCanaryRunner",
]
