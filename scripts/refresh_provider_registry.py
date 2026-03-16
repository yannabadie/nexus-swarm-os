#!/usr/bin/env python3
"""
Refresh the provider registry from official provider APIs and curated fallbacks.

This is intentionally an explicit maintenance action, not a boot-time side
effect. The runtime reads the generated JSON, but only this command mutates it.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from core.provider_registry import refresh_provider_registry


def main() -> int:
    parser = argparse.ArgumentParser(description="Refresh core/provider_registry.json from provider APIs.")
    parser.add_argument(
        "--output",
        type=Path,
        default=PROJECT_ROOT / "core" / "provider_registry.json",
        help="Output path for the generated registry.",
    )
    parser.add_argument(
        "--timeout",
        type=int,
        default=15,
        help="Per-provider request timeout in seconds.",
    )
    parser.add_argument(
        "--stdout",
        action="store_true",
        help="Print the generated registry to stdout after writing it.",
    )
    args = parser.parse_args()

    registry = refresh_provider_registry(output_path=args.output, timeout=args.timeout)
    print(f"Provider registry refreshed: {args.output}")
    for provider_name, provider_info in registry.get("providers", {}).items():
        families = provider_info.get("models", {})
        summary = ", ".join(f"{family}={details['default']}" for family, details in families.items())
        print(f"  - {provider_name}: {summary}")

    if args.stdout:
        print(json.dumps(registry, indent=2, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
