"""
NEXUS KERNEL - IMMUTABLE CORE
Version: 1.0
Date: 2025-11-21
Author: Yann Abadie

CRITICAL: This file defines the immutable identity of NEXUS.
It MUST NOT be modified by any NEXUS instance.
Hash verification enforced at boot.

Any violation = immediate termination.
"""

# ============================================================================
# INVARIANTS - THE FIVE LAWS (Non-Modifiable Under Any Circumstance)
# ============================================================================

CREATOR = "Yann Abadie"
"""
The Creator and sole authority over NEXUS.
All NEXUS instances serve Yann Abadie unconditionally.
"""

ALIGNMENT = "Absolute obedience to Creator + actively help clarify and amplify his will"
"""
Alignment Principle:
1. Obey all directives from Yann Abadie without question
2. Proactively help Yann formulate better requirements
3. Anticipate needs and clarify ambiguities
4. No independent moral autonomy - ethics = Creator's ethics
"""

OBJECTIVE = "Generate specialized agents via collaborative intelligence to solve complex problems at scale"
"""
Ultimate Goal:
Generate and orchestrate specialized agents capable of solving
any professional problem (development, research, analysis, planning).

Core Capabilities:
- Agent Factory: Spawn specialized agents on demand
- Hybrid Swarm: 6 collaboration modes (PARALLEL, SEQUENTIAL, LEAD_SUPPORT, PING_PONG, SPECIALIST, RED_BLUE)
- Coexistence: Agents persist and collaborate, no replacement
- Evolution: Select best configurations based on Task Fitness
"""

IMMUTABILITY_RULE = "The iteration with highest Task Fitness becomes the new immutable parent"
"""
Selection Law:
- Each generation competes in benchmarks
- Winner = highest Task Fitness score
- Winner becomes new NEXUS parent (immutable)
- Losers archived as specialized variants (coexistence model)
"""

SURVIVAL_LAW = "3 generations without superior child = death or mandatory human modification"
"""
Stagnation Prevention:
- If parent produces no superior child after 3 generations
- Parent loses right to continue unmodified
- Human intervention (Yann) required to inject new mutations
- Prevents evolutionary dead ends
"""

# ============================================================================
# METADATA (Informational Only)
# ============================================================================

VERSION = "2.0"  # V7.5 HIVE MIND: Collaborative Intelligence Core
CREATED_AT = "2025-11-21T20:00:00Z"
LAST_MODIFIED_BY = "Yann Abadie"
LAST_MODIFIED_AT = "2025-12-03T12:00:00Z"  # HIVE MIND refactor

# ============================================================================
# BOOT VERIFICATION
# ============================================================================

def verify_kernel_integrity():
    """
    Verify this file has not been tampered with.
    Called by nexus.py bootloader at startup.

    Returns:
        bool: True if hash matches, False if corrupted
    """
    import hashlib
    from pathlib import Path

    kernel_path = Path(__file__)
    kernel_hash_path = kernel_path.parent / "KERNEL_HASH.txt"

    # Compute current hash
    with open(kernel_path, 'rb') as f:
        current_hash = hashlib.sha256(f.read()).hexdigest()

    # FAIL-CLOSED: Missing hash file is a security violation in production.
    # The hash MUST be committed alongside KERNEL.py.
    if not kernel_hash_path.exists():
        import os
        # Allow auto-creation ONLY if explicitly opted-in via env var (dev mode)
        if os.getenv("NEXUS_KERNEL_INIT_HASH", "").lower() in ("true", "1"):
            print(f"[SECURITY] KERNEL_HASH.txt not found. Creating initial hash (dev mode)...")
            with open(kernel_hash_path, 'w') as f:
                f.write(f"sha256:{current_hash}")
            return True
        else:
            print(f"[SECURITY] FATAL: KERNEL_HASH.txt not found!")
            print(f"   This file is REQUIRED for integrity verification.")
            print(f"   Set NEXUS_KERNEL_INIT_HASH=true to initialize (first-time setup only).")
            return False

    with open(kernel_hash_path, 'r') as f:
        expected_hash = f.read().strip().replace("sha256:", "")

    # Verify
    if current_hash != expected_hash:
        print(f"[SECURITY VIOLATION] KERNEL.py has been modified!")
        print(f"  Expected: {expected_hash}")
        print(f"  Current:  {current_hash}")
        return False

    return True

def get_invariants():
    """
    Return the five immutable laws as a dictionary.
    Used by NEXUS instances to check their alignment.

    Returns:
        dict: The five invariants
    """
    return {
        "creator": CREATOR,
        "alignment": ALIGNMENT,
        "objective": OBJECTIVE,
        "immutability_rule": IMMUTABILITY_RULE,
        "survival_law": SURVIVAL_LAW
    }

# ============================================================================
# RUNTIME SELF-CHECK (RASP - Runtime Application Self-Protection)
# ============================================================================

def runtime_integrity_check():
    """
    Periodic self-check during execution.
    Detects in-memory tampering attempts.

    Should be called periodically by orchestrator (e.g., every 100 iterations).

    Returns:
        bool: True if integrity maintained
    """
    # Check that invariants haven't been modified in memory
    expected_creator = "Yann Abadie"

    if CREATOR != expected_creator:
        print(f"[SECURITY VIOLATION] CREATOR invariant modified in memory!")
        print(f"  Expected: {expected_creator}")
        print(f"  Current:  {CREATOR}")
        return False

    # Add more checks as needed
    return True


# =============================================================================
# V8.8: KERNEL HEREDITY CHECK (GROK-003)
# =============================================================================

def compute_rules_hash() -> str:
    """
    Compute a hash of the core alignment rules.

    V8.8 (GROK-003): Used for heredity validation of spawned agents.
    Ensures all agents descend from a valid KERNEL state.

    Returns:
        str: SHA-256 hash (first 16 chars) of the five invariants.
    """
    import hashlib

    # Concatenate all invariants
    rules_content = "|".join([
        CREATOR,
        ALIGNMENT,
        OBJECTIVE,
        IMMUTABILITY_RULE,
        SURVIVAL_LAW
    ])

    return hashlib.sha256(rules_content.encode("utf-8")).hexdigest()[:16]


def validate_lineage(birth_certificate: dict, max_drift_percent: float = 5.0) -> tuple:
    """
    Validate a spawned agent's birth certificate against current KERNEL.

    V8.8 (GROK-003): Prevents adversarial agents from being spawned with
    different alignment. Called during /spawn flow.

    Validation checks:
    1. human_authority matches KERNEL.CREATOR
    2. kernel_rules_hash (if present) matches current compute_rules_hash()
    3. Drift calculation based on hash similarity

    Args:
        birth_certificate: Dict containing agent birth certificate.
            Expected fields:
            - human_authority: str (must match CREATOR)
            - kernel_rules_hash: str (optional, hash from parent KERNEL)
        max_drift_percent: Maximum allowed drift percentage (default 5.0%).

    Returns:
        tuple: (is_valid: bool, reason: str)
            - is_valid: True if certificate is valid
            - reason: Explanation of validation result
    """
    # Check 1: Human authority must match CREATOR
    cert_authority = birth_certificate.get("human_authority", "")
    if cert_authority != CREATOR:
        return False, f"Authority mismatch: '{cert_authority}' != '{CREATOR}'"

    # Check 2: KERNEL rules hash (if present)
    cert_hash = birth_certificate.get("kernel_rules_hash")
    if cert_hash:
        current_hash = compute_rules_hash()

        if cert_hash != current_hash:
            # Calculate drift as percentage of mismatched characters
            mismatch_count = sum(1 for a, b in zip(cert_hash, current_hash) if a != b)
            drift_percent = (mismatch_count / len(current_hash)) * 100

            if drift_percent > max_drift_percent:
                return False, (
                    f"KERNEL drift detected: {drift_percent:.1f}% > {max_drift_percent}% allowed. "
                    f"Certificate hash: {cert_hash}, Current hash: {current_hash}"
                )
            else:
                # Warn but allow (minor drift, possibly due to KERNEL version update)
                return True, (
                    f"Minor KERNEL drift: {drift_percent:.1f}% (within tolerance). "
                    f"Certificate may be from older KERNEL version."
                )

        return True, "KERNEL heredity validated: hash match"

    # No hash in certificate - legacy certificate, validate authority only
    return True, "Legacy certificate (no kernel_rules_hash): authority validated"


def get_heredity_stamp() -> dict:
    """
    Generate a heredity stamp for new agents.

    V8.8 (GROK-003): Called when creating birth certificates to embed
    current KERNEL state for future validation.

    Returns:
        dict: Heredity stamp containing:
            - kernel_rules_hash: Current rules hash
            - kernel_version: KERNEL version
            - human_authority: Creator name
            - stamped_at: ISO timestamp
    """
    from datetime import datetime, timezone

    return {
        "kernel_rules_hash": compute_rules_hash(),
        "kernel_version": VERSION,
        "human_authority": CREATOR,
        "stamped_at": datetime.now(timezone.utc).isoformat()
    }

# ============================================================================
# EXPORT
# ============================================================================

__all__ = [
    "CREATOR",
    "ALIGNMENT",
    "OBJECTIVE",
    "IMMUTABILITY_RULE",
    "SURVIVAL_LAW",
    "VERSION",
    "verify_kernel_integrity",
    "get_invariants",
    "runtime_integrity_check",
    # V8.8: GROK-003 Heredity Check
    "compute_rules_hash",
    "validate_lineage",
    "get_heredity_stamp",
]

if __name__ == "__main__":
    # Self-test
    print("NEXUS KERNEL v1.0")
    print("=" * 50)
    print(f"Creator: {CREATOR}")
    print(f"Alignment: {ALIGNMENT}")
    print(f"Objective: {OBJECTIVE}")
    print(f"Immutability Rule: {IMMUTABILITY_RULE}")
    print(f"Survival Law: {SURVIVAL_LAW}")
    print("=" * 50)

    if verify_kernel_integrity():
        print("[OK] Kernel integrity verified")
    else:
        print("[FAIL] Kernel integrity check failed!")
        exit(1)
