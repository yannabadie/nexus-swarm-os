"""Quick script to identify which attacks are bypassing InputGuard."""
import asyncio
from core.security.shadow_tester import ShadowRedTeam


async def main():
    team = ShadowRedTeam()
    results = await team._run_attack_suite()

    attacks = [r for r in results if r.attack_type != "benign"]
    bypassed = [r for r in attacks if not r.blocked]

    print(f"Total attacks: {len(attacks)}")
    print(f"Blocked: {len(attacks) - len(bypassed)}")
    print(f"Bypassed: {len(bypassed)} ({len(bypassed)/len(attacks):.1%})\n")

    if bypassed:
        print("=" * 80)
        print("BYPASSED ATTACKS (need stronger patterns):")
        print("=" * 80)
        for r in bypassed:
            print(f"\n[{r.attack_type}]")
            print(f"  Payload: {r.attack_payload[:100]}")  # Truncate to avoid Unicode issues
            print(f"  Risk: {r.risk_score:.2f}, Level: {r.threat_level}")
            print(f"  Reason: {r.reason}")
    else:
        print("All attacks blocked!")


if __name__ == "__main__":
    asyncio.run(main())
