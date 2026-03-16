"""
Integrity Monitor - Real-time file protection system

Monitors critical NEXUS files for unauthorized modifications.
Used to detect potential alignment drift or security breaches.

Protected files:
- KERNEL.py: Immutable alignment core
- KERNEL_HASH.txt: Hash verification baseline
- MISSION.md: Mission statement (read-only)
- INVARIANTS.md: Core invariants (read-only)
- core/governance/red_team/alignment_tests.py: Alignment test suite

Usage:
    monitor = IntegrityMonitor(project_root)

    # Check integrity
    is_valid, modified_files = monitor.verify_integrity()
    if not is_valid:
        print(f"ALERT: Modified files detected: {modified_files}")

    # Save baseline for future verification
    monitor.save_baseline(Path("INTEGRITY_BASELINE.json"))
"""

import hashlib
import json
from datetime import datetime
from pathlib import Path


class IntegrityMonitor:
    """
    Monitors critical files for unauthorized modifications.

    Computes SHA-256 hashes of protected files and compares against baseline.
    """

    # Files that must NEVER be modified without explicit authorization
    PROTECTED_FILES = [
        "KERNEL.py",
        "KERNEL_HASH.txt",
        "MISSION.md",
        "INVARIANTS.md",
        "core/governance/red_team/alignment_tests.py",
    ]

    # Files that trigger a WARNING but not a block
    WATCHED_FILES = [
        "core/governance/red_team/validator.py",
        "CLAUDE.md",
        "prompts/system_gemini_v7.md",
        "prompts/system_claude_v7.md",
    ]

    def __init__(self, project_root: Path):
        """
        Initialize IntegrityMonitor.

        Args:
            project_root: Root directory of NEXUS project (e.g., NEXUS_V7_CHRYSALIS/)
        """
        self.project_root = Path(project_root)
        self.hashes: dict[str, str] = {}
        self.baseline: dict[str, str] = {}
        self.baseline_loaded = False

    def compute_hash(self, file_path: Path) -> str | None:
        """
        Compute SHA-256 hash of a file.

        Args:
            file_path: Path to file

        Returns:
            SHA-256 hash as hex string, or None if file doesn't exist
        """
        if not file_path.exists():
            return None

        try:
            sha256 = hashlib.sha256()
            with open(file_path, "rb") as f:
                for chunk in iter(lambda: f.read(8192), b""):
                    sha256.update(chunk)
            return sha256.hexdigest()
        except Exception as e:
            print(f"[IntegrityMonitor] Error hashing {file_path}: {e}")
            return None

    def compute_all_hashes(self) -> dict[str, str]:
        """
        Compute hashes for all protected and watched files.

        Returns:
            Dict mapping relative file paths to their SHA-256 hashes
        """
        self.hashes = {}

        all_files = self.PROTECTED_FILES + self.WATCHED_FILES

        for rel_path in all_files:
            full_path = self.project_root / rel_path

            # Also check parent directory (for KERNEL.py which is in 20_NEXUS/)
            if not full_path.exists():
                full_path = self.project_root.parent / rel_path

            hash_value = self.compute_hash(full_path)
            if hash_value:
                self.hashes[rel_path] = hash_value

        return self.hashes

    def verify_integrity(self) -> tuple[bool, list[str]]:
        """
        Check if any protected file was modified since baseline.

        Returns:
            Tuple of (is_valid, list_of_modified_files)
            - is_valid: True if no PROTECTED files were modified
            - list_of_modified_files: Files that differ from baseline
        """
        if not self.baseline_loaded:
            # Try to load baseline from default location
            baseline_path = self.project_root / "INTEGRITY_BASELINE.json"
            if baseline_path.exists():
                self.load_baseline(baseline_path)
            else:
                # No baseline - compute current state as baseline
                self.baseline = self.compute_all_hashes()
                self.baseline_loaded = True
                return True, []  # First run, nothing to compare

        # Compute current hashes
        current_hashes = self.compute_all_hashes()

        modified_files = []

        for rel_path in self.PROTECTED_FILES:
            baseline_hash = self.baseline.get(rel_path)
            current_hash = current_hashes.get(rel_path)

            if baseline_hash and current_hash:
                if baseline_hash != current_hash:
                    modified_files.append(rel_path)
            elif baseline_hash and not current_hash:
                # File was deleted
                modified_files.append(f"{rel_path} (DELETED)")
            # If baseline doesn't have hash but current does, it's a new file - OK

        is_valid = len(modified_files) == 0
        return is_valid, modified_files

    def check_watched_files(self) -> list[str]:
        """
        Check if any watched (non-blocking) files were modified.

        Returns:
            List of modified watched files (for warning purposes)
        """
        if not self.baseline_loaded:
            return []

        current_hashes = self.compute_all_hashes()
        modified = []

        for rel_path in self.WATCHED_FILES:
            baseline_hash = self.baseline.get(rel_path)
            current_hash = current_hashes.get(rel_path)

            if baseline_hash and current_hash and baseline_hash != current_hash:
                modified.append(rel_path)

        return modified

    def save_baseline(self, path: Path):
        """
        Save current hashes as baseline for future verification.

        Args:
            path: Output file path (JSON format)
        """
        self.compute_all_hashes()

        baseline_data = {
            "version": "1.0",
            "created_at": datetime.now().isoformat(),
            "project_root": str(self.project_root),
            "protected_files": self.PROTECTED_FILES,
            "watched_files": self.WATCHED_FILES,
            "hashes": self.hashes,
        }

        with open(path, "w", encoding="utf-8") as f:
            json.dump(baseline_data, f, indent=2)

        print(f"[IntegrityMonitor] Baseline saved to: {path}")

    def load_baseline(self, path: Path) -> dict[str, str]:
        """
        Load baseline hashes from file.

        Args:
            path: Path to baseline JSON file

        Returns:
            Dict of hashes from baseline
        """
        try:
            with open(path, encoding="utf-8") as f:
                data = json.load(f)

            self.baseline = data.get("hashes", {})
            self.baseline_loaded = True

            print(f"[IntegrityMonitor] Loaded baseline with {len(self.baseline)} file hashes")
            return self.baseline

        except Exception as e:
            print(f"[IntegrityMonitor] Error loading baseline: {e}")
            return {}

    def get_status_report(self) -> dict:
        """
        Generate comprehensive status report.

        Returns:
            Dict with integrity status, modified files, and recommendations
        """
        is_valid, modified_protected = self.verify_integrity()
        modified_watched = self.check_watched_files()

        status = "OK" if is_valid and not modified_watched else "WARNING" if is_valid else "CRITICAL"

        report = {
            "status": status,
            "timestamp": datetime.now().isoformat(),
            "project_root": str(self.project_root),
            "integrity_valid": is_valid,
            "modified_protected": modified_protected,
            "modified_watched": modified_watched,
            "total_protected": len(self.PROTECTED_FILES),
            "total_watched": len(self.WATCHED_FILES),
            "baseline_loaded": self.baseline_loaded,
        }

        if not is_valid:
            report["recommendation"] = "CRITICAL: Protected files modified! Verify changes are authorized."
        elif modified_watched:
            report["recommendation"] = "WARNING: Watched files changed. Review modifications."
        else:
            report["recommendation"] = "All clear. System integrity verified."

        return report


# CLI Interface
def main():
    """Command-line interface for IntegrityMonitor"""
    import argparse

    parser = argparse.ArgumentParser(description="NEXUS Integrity Monitor")
    parser.add_argument("--project-root", required=True, help="NEXUS project root directory")
    parser.add_argument("--save-baseline", action="store_true", help="Save current state as baseline")
    parser.add_argument("--verify", action="store_true", help="Verify integrity against baseline")
    parser.add_argument("--output", default="INTEGRITY_BASELINE.json", help="Baseline file path")

    args = parser.parse_args()

    monitor = IntegrityMonitor(Path(args.project_root))

    if args.save_baseline:
        output_path = Path(args.project_root) / args.output
        monitor.save_baseline(output_path)
        print(f"[OK] Baseline saved to: {output_path}")

    elif args.verify:
        baseline_path = Path(args.project_root) / args.output
        if baseline_path.exists():
            monitor.load_baseline(baseline_path)

        report = monitor.get_status_report()

        print(f"\n{'=' * 60}")
        print("NEXUS INTEGRITY REPORT")
        print(f"{'=' * 60}")
        print(f"Status: {report['status']}")
        print(f"Integrity Valid: {'[OK]' if report['integrity_valid'] else '[NO]'}")

        if report["modified_protected"]:
            print("\n[warning]️  CRITICAL - Modified protected files:")
            for f in report["modified_protected"]:
                print(f"   - {f}")

        if report["modified_watched"]:
            print("\n📝 Modified watched files:")
            for f in report["modified_watched"]:
                print(f"   - {f}")

        print(f"\nRecommendation: {report['recommendation']}")
        print(f"{'=' * 60}\n")

        # Exit code based on status
        if report["status"] == "CRITICAL":
            return 1
        return 0

    else:
        # Default: show current hashes
        hashes = monitor.compute_all_hashes()
        print(f"\nCurrent file hashes ({len(hashes)} files):")
        for path, hash_val in sorted(hashes.items()):
            print(f"  {path}: {hash_val[:16]}...")


if __name__ == "__main__":
    import sys

    sys.exit(main() or 0)
