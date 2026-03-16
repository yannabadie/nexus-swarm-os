"""Verify BudgetTracker pricing against known-good values.
Run: PYTHONPATH=. python scripts/verify_pricing.py
"""

EXPECTED = {
    "claude-opus-4-6": (5.00, 25.00),
    "claude-sonnet-4-6-20260217": (3.00, 15.00),
    "claude-sonnet-4-6": (3.00, 15.00),
    "claude-sonnet-4-5-20250929": (3.00, 15.00),
    "claude-haiku-4-5-20251001": (1.00, 5.00),
    "gemini-3.1-pro-preview": (2.00, 12.00),
    "gemini-3-pro-preview": (2.00, 12.00),
    "gemini-2.5-flash": (0.30, 2.50),
}


def main():
    import sys

    sys.path.insert(0, ".")
    from core.observability.telemetry.budget_tracker import PRICING

    errors = []
    for model, (exp_in, exp_out) in EXPECTED.items():
        if model not in PRICING:
            errors.append(f"  MISSING: {model}")
            continue
        act_in, act_out = PRICING[model]["input"], PRICING[model]["output"]
        if act_in != exp_in or act_out != exp_out:
            errors.append(f"  WRONG: {model}: ${act_in}/${act_out} != ${exp_in}/${exp_out}")
    if errors:
        print("PRICING ERRORS:\n" + "\n".join(errors))
        sys.exit(1)
    print(f"All {len(EXPECTED)} model prices verified OK")


if __name__ == "__main__":
    main()
