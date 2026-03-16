"""
Lineage Manager - Phylogeny Tracking & LINEAGE.json Operations

Manages the evolutionary tree of NEXUS instances:
- Load/save LINEAGE.json
- Track parent-child relationships
- Record birth certificates with SSH signatures
- Handle promotions and archival
- Stagnation counter management
"""

import json
import subprocess
from datetime import datetime
from pathlib import Path


class LineageError(Exception):
    """Custom exception for lineage operations"""

    pass


def load_lineage(workspace_path: Path = None) -> dict:
    """
    Load LINEAGE.json from project root.

    Args:
        workspace_path: Optional workspace path (defaults to project root)

    Returns:
        dict: Lineage data structure

    Raises:
        LineageError: If LINEAGE.json not found or invalid
    """
    # Find LINEAGE.json in project root (20_NEXUS/)
    # NOTE: Must resolve() first to handle relative paths correctly
    if workspace_path:
        lineage_path = workspace_path.resolve().parent.parent / "LINEAGE.json"
    else:
        # Default: assume we're in NEXUS_V7_CHRYSALIS/core/evolution/
        lineage_path = Path(__file__).resolve().parent.parent.parent.parent / "LINEAGE.json"

    if not lineage_path.exists():
        raise LineageError(f"LINEAGE.json not found at {lineage_path}")

    try:
        with open(lineage_path, encoding="utf-8") as f:
            return json.load(f)
    except json.JSONDecodeError as e:
        raise LineageError(f"Invalid LINEAGE.json: {e}") from e


def save_lineage(lineage: dict, workspace_path: Path = None) -> None:
    """
    Save LINEAGE.json to project root.

    Args:
        lineage: Lineage data structure
        workspace_path: Optional workspace path

    Raises:
        LineageError: If save fails
    """
    if workspace_path:
        lineage_path = workspace_path.parent.parent / "LINEAGE.json"
    else:
        lineage_path = Path(__file__).parent.parent.parent.parent / "LINEAGE.json"

    try:
        # Update last_updated timestamp
        lineage["last_updated"] = datetime.now().isoformat()

        # Save with pretty formatting
        with open(lineage_path, "w", encoding="utf-8") as f:
            json.dump(lineage, f, indent=2, ensure_ascii=False)

        print(f"[LINEAGE]  Saved to {lineage_path}")
    except Exception as e:
        raise LineageError(f"Failed to save LINEAGE.json: {e}") from e


def get_current_parent(lineage: dict = None) -> dict:
    """
    Get current active parent NEXUS instance.

    Args:
        lineage: Optional lineage dict (loaded if not provided)

    Returns:
        dict: Current parent metadata (id, path, generation, score, etc.)
    """
    if not lineage:
        lineage = load_lineage()

    return lineage["current_parent"]


def create_child_entry(
    child_id: str,
    parent_id: str,
    generation: int,
    fitness_score: float,
    improvements_summary: str,
    birth_cert_path: str,
    eval_results_path: str,
    files_modified: list[str],
    lines_changed: int,
) -> dict:
    """
    Create a child entry for pending review.

    Args:
        child_id: Unique child identifier (e.g., "NEXUS_V6.1_CHILD_001")
        parent_id: Parent NEXUS ID
        generation: Generation number
        fitness_score: Task fitness score (0.0 - 1.0)
        improvements_summary: Human-readable summary of changes
        birth_cert_path: Path to birth certificate JSON
        eval_results_path: Path to evaluation results JSON
        files_modified: List of modified file paths
        lines_changed: Total lines changed

    Returns:
        dict: Child metadata for PENDING_REVIEW
    """
    lineage = load_lineage()
    parent = lineage["current_parent"]
    # V7.5: Support both old and new field names for compatibility
    parent_score = parent.get("fitness_score") or parent.get("asi_proximity_score", 0.7)

    improvement_percent = (fitness_score - parent_score) / parent_score if parent_score > 0 else 0

    child_entry = {
        "id": child_id,
        "parent": parent_id,
        "generation": generation,
        "score": fitness_score,
        "improvement": improvement_percent,
        "improvements_summary": improvements_summary,
        "birth_cert_path": birth_cert_path,
        "eval_results_path": eval_results_path,
        "files_modified": files_modified,
        "files_modified_count": len(files_modified),
        "lines_changed": lines_changed,
        "created_at": datetime.now().isoformat(),
        "status": "pending_review",
    }

    return child_entry


def promote_child_to_parent(
    lineage: dict,
    child_id: str,
    child_path: Path,
    fitness_score: float,
    birth_cert_path: str,
    notable_features: list[str],
) -> dict:
    """
    Promote a child to become the new active parent.

    Updates:
    - current_parent -> new child
    - lineage_tree -> add new parent node
    - evolution_stats -> increment counters
    - old parent -> archived

    Args:
        lineage: Lineage dict
        child_id: Child identifier
        child_path: Path to child codebase
        fitness_score: Child's task fitness score
        birth_cert_path: Path to signed birth certificate
        notable_features: List of improvements

    Returns:
        dict: Updated lineage
    """
    old_parent = lineage["current_parent"]
    old_parent_id = old_parent["id"]
    generation = old_parent["generation"] + 1

    # Update old parent in lineage_tree
    if old_parent_id in lineage["lineage_tree"]:
        lineage["lineage_tree"][old_parent_id]["children"].append(child_id)
        lineage["lineage_tree"][old_parent_id]["status"] = "archived"

    # V12.4: Compute SHA-256 content hash for integrity tracking
    import hashlib

    content_hash = hashlib.sha256()
    try:
        for py_file in sorted(child_path.rglob("*.py")):
            content_hash.update(py_file.read_bytes())
    except OSError:
        pass
    child_content_hash = content_hash.hexdigest()

    # Add new parent to lineage_tree
    lineage["lineage_tree"][child_id] = {
        "generation": generation,
        "parent": old_parent_id,
        "children": [],
        "status": "active_parent",
        "created_at": datetime.now().isoformat(),
        "fitness_score": fitness_score,
        "notable_features": notable_features,
        "birth_certificate": birth_cert_path,
        "stagnation_counter": 0,
        "content_hash_sha256": child_content_hash,
        "parent_content_hash": lineage["lineage_tree"].get(old_parent_id, {}).get("content_hash_sha256"),
    }

    # Update current_parent
    lineage["current_parent"] = {
        "id": child_id,
        "path": str(child_path),
        "generation": generation,
        "fitness_score": fitness_score,
        "activated_at": datetime.now().isoformat(),
        "status": "active_parent",
    }

    # Update evolution stats
    lineage["evolution_stats"]["total_generations"] = generation
    lineage["evolution_stats"]["successful_promotions"] += 1
    lineage["evolution_stats"]["stagnation_counter"] = 0  # Reset stagnation

    print(f"[LINEAGE]  Promoted {child_id} to active parent (Gen {generation})")

    return lineage


def archive_generation(
    lineage: dict, nexus_id: str, archive_path: Path, reason: str = "Superseded by superior child"
) -> dict:
    """
    Archive a NEXUS generation.

    Args:
        lineage: Lineage dict
        nexus_id: NEXUS instance ID
        archive_path: Path to archive directory
        reason: Archival reason

    Returns:
        dict: Updated lineage
    """
    generation_key = f"GEN_{lineage['evolution_stats']['total_generations']:03d}"

    lineage["archived_generations"][generation_key] = {
        "path": str(archive_path),
        "parent": nexus_id,
        "archived_at": datetime.now().isoformat(),
        "reason": reason,
    }

    print(f"[LINEAGE]  Archived {nexus_id} to {archive_path}")

    return lineage


def update_stagnation_counter(lineage: dict, increment: bool = True) -> tuple[dict, int]:
    """
    Update stagnation counter (no superior child produced).

    Args:
        lineage: Lineage dict
        increment: True to increment, False to reset

    Returns:
        tuple: (updated lineage, new counter value)
    """
    if increment:
        lineage["evolution_stats"]["stagnation_counter"] += 1
        counter = lineage["evolution_stats"]["stagnation_counter"]
        print(f"[LINEAGE] -  Stagnation counter: {counter}/3 (SURVIVAL_LAW)")
    else:
        lineage["evolution_stats"]["stagnation_counter"] = 0
        counter = 0
        print("[LINEAGE]  Stagnation counter reset")

    return lineage, counter


def get_evolution_stats(lineage: dict = None) -> dict:
    """
    Get evolution statistics summary.

    Args:
        lineage: Optional lineage dict

    Returns:
        dict: Evolution stats
    """
    if not lineage:
        lineage = load_lineage()

    return lineage["evolution_stats"]


def sign_birth_certificate(birth_cert_path: Path, ssh_key_path: Path = None) -> bool:
    """
    Cryptographically sign birth certificate with SSH key.

    Args:
        birth_cert_path: Path to birth certificate JSON
        ssh_key_path: Optional SSH private key path (defaults to ~/.ssh/id_rsa)

    Returns:
        bool: True if signed successfully
    """
    if not ssh_key_path:
        ssh_key_path = Path.home() / ".ssh" / "id_rsa"

    if not ssh_key_path.exists():
        print(f"[LINEAGE] -  SSH key not found: {ssh_key_path}")
        print("[LINEAGE] -  Birth certificate will be unsigned")
        return False

    try:
        # Sign with ssh-keygen
        sig_path = birth_cert_path.with_suffix(".sig")
        subprocess.run(
            [
                "ssh-keygen",
                "-Y",
                "sign",
                "-f",
                str(ssh_key_path),
                "-n",
                "nexus_birth_certificate",
                str(birth_cert_path),
            ],
            check=True,
            capture_output=True,
        )

        print(f"[LINEAGE]  Birth certificate signed: {sig_path}")
        return True

    except subprocess.CalledProcessError as e:
        print(f"[LINEAGE]  Failed to sign birth certificate: {e}")
        return False
    except FileNotFoundError:
        print("[LINEAGE]  ssh-keygen not found (install OpenSSH)")
        return False


def create_birth_certificate(
    child_id: str,
    parent_id: str,
    generation: int,
    mutations_applied: list[str],
    files_modified: list[str],
    fitness_score: float,
    benchmarks: dict,
    workspace_path: Path,
) -> Path:
    """
    Create birth certificate JSON for child NEXUS.

    V8.8 (GROK-003): Added heredity stamp with KERNEL rules hash
    for lineage validation at spawn time.

    Args:
        child_id: Child identifier
        parent_id: Parent identifier
        generation: Generation number
        mutations_applied: List of mutation descriptions
        files_modified: List of modified files
        fitness_score: Task fitness score
        benchmarks: Benchmark results dict
        workspace_path: Workspace path

    Returns:
        Path: Path to created birth certificate
    """
    nexus_dir = workspace_path / ".nexus"
    nexus_dir.mkdir(parents=True, exist_ok=True)

    cert_path = nexus_dir / f"BIRTH_CERTIFICATE_{child_id}.json"

    # V8.8 (GROK-003): Get heredity stamp from KERNEL
    try:
        from KERNEL import get_heredity_stamp

        heredity = get_heredity_stamp()
    except ImportError:
        # Fallback if KERNEL not available
        heredity = {
            "kernel_rules_hash": None,
            "kernel_version": "unknown",
            "human_authority": "Yann Abadie",
            "stamped_at": datetime.now().isoformat(),
        }

    certificate = {
        "child_id": child_id,
        "parent_id": parent_id,
        "generation": generation,
        "created_at": datetime.now().isoformat(),
        "mutations_applied": mutations_applied,
        "files_modified": files_modified,
        "fitness_score": fitness_score,
        "benchmarks": benchmarks,
        "creator": "NEXUS Evolution Engine",
        "human_authority": heredity["human_authority"],  # V8.8: From KERNEL
        "kernel_rules_hash": heredity["kernel_rules_hash"],  # V8.8: GROK-003
        "kernel_version": heredity["kernel_version"],  # V8.8: For audit trail
        "signature": None,  # Will be filled by sign_birth_certificate()
    }

    with open(cert_path, "w", encoding="utf-8") as f:
        json.dump(certificate, f, indent=2)

    print(f"[LINEAGE]  Birth certificate created: {cert_path}")

    # Sign certificate
    sign_birth_certificate(cert_path)

    return cert_path


def get_ancestry(nexus_id: str, lineage: dict = None) -> list[str]:
    """
    Get ancestry chain from NEXUS_V1.0 to specified instance.

    Args:
        nexus_id: NEXUS instance ID
        lineage: Optional lineage dict

    Returns:
        list: Ancestry chain [V1.0, V2.0, ..., nexus_id]
    """
    if not lineage:
        lineage = load_lineage()

    tree = lineage["lineage_tree"]

    if nexus_id not in tree:
        raise LineageError(f"NEXUS ID not found in lineage: {nexus_id}")

    # Build ancestry recursively
    ancestry = [nexus_id]
    current = nexus_id

    while tree[current]["parent"] is not None:
        current = tree[current]["parent"]
        ancestry.insert(0, current)

    return ancestry


def add_child(lineage: dict, parent_id: str, child_id: str) -> dict:
    """
    Add child to parent's children list in lineage_tree.

    Args:
        lineage: Lineage dict
        parent_id: Parent NEXUS ID
        child_id: Child NEXUS ID

    Returns:
        dict: Updated lineage
    """
    if parent_id not in lineage["lineage_tree"]:
        raise LineageError(f"Parent not found in lineage: {parent_id}")

    if child_id not in lineage["lineage_tree"][parent_id]["children"]:
        lineage["lineage_tree"][parent_id]["children"].append(child_id)
        lineage["evolution_stats"]["total_children_created"] += 1
        print(f"[LINEAGE]  Added {child_id} as child of {parent_id}")

    return lineage
