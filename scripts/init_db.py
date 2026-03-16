#!/usr/bin/env python3
"""
NEXUS V12.2 IRONCLAD - Database Bootstrap Script

Creates the initial database with:
- Default tenant
- Admin user (password from NEXUS_ADMIN_PASSWORD or 'nexus')
- Default workspace
- Quota configuration

Usage:
    python scripts/init_db.py

Environment Variables:
    NEXUS_ADMIN_PASSWORD: Password for admin user (default: 'nexus')
    NEXUS_ADMIN_EMAIL: Email for admin user (default: 'admin@nexus.local')

Author: Claude (NEXUS V12.2 IRONCLAD)
Date: 2025-12-16
"""

import os
import sys
from pathlib import Path
from uuid import UUID

# Add project root to path for imports
project_root = Path(__file__).parent.parent
sys.path.insert(0, str(project_root))

from sqlmodel import select

from core.infrastructure.db import (
    init_db,
    get_session,
    Tenant,
    User,
    Workspace,
    Quota,
    PlanTier,
    TenantStatus,
    create_quota_for_plan,
)
from core.infrastructure.db.models import UserRole

# V12.4: Use centralized password module (argon2-cffi)
from core.security_pkg.security.password import hash_password, verify_password


# =============================================================================
# Bootstrap Configuration
# =============================================================================

# Fixed UUIDs for default entities (deterministic for reproducibility)
DEFAULT_TENANT_ID = UUID("00000000-0000-0000-0000-000000000001")
DEFAULT_ADMIN_ID = UUID("00000000-0000-0000-0000-000000000002")
DEFAULT_WORKSPACE_ID = UUID("00000000-0000-0000-0000-000000000003")

# Configuration from environment
ADMIN_PASSWORD = os.environ.get("NEXUS_ADMIN_PASSWORD", "nexus")
ADMIN_EMAIL = os.environ.get("NEXUS_ADMIN_EMAIL", "admin@nexus.local")
ADMIN_USERNAME = "admin"


# =============================================================================
# Bootstrap Functions
# =============================================================================

def check_existing_admin(session) -> bool:
    """Check if admin user already exists."""
    statement = select(User).where(User.id == DEFAULT_ADMIN_ID)
    return session.exec(statement).first() is not None


def check_existing_tenant(session) -> bool:
    """Check if default tenant already exists."""
    statement = select(Tenant).where(Tenant.id == DEFAULT_TENANT_ID)
    return session.exec(statement).first() is not None


def create_default_entities(session) -> dict:
    """
    Create default tenant, admin user, workspace, and quota.

    Returns:
        Dict with created entity info
    """
    created = {}

    # 1. Create default tenant
    if not check_existing_tenant(session):
        tenant = Tenant(
            id=DEFAULT_TENANT_ID,
            name="Default",
            slug="default",
            plan_tier=PlanTier.PRO,  # Full features for local dev
            status=TenantStatus.ACTIVE,
            email=ADMIN_EMAIL,
        )
        session.add(tenant)
        created["tenant"] = {"id": str(DEFAULT_TENANT_ID), "name": "Default"}
        print(f"[+] Created tenant: Default (id={DEFAULT_TENANT_ID})")
    else:
        print(f"[=] Tenant 'Default' already exists")

    # 2. Create admin user with hashed password
    if not check_existing_admin(session):
        hashed_pw = hash_password(ADMIN_PASSWORD)
        admin = User(
            id=DEFAULT_ADMIN_ID,
            tenant_id=DEFAULT_TENANT_ID,
            username=ADMIN_USERNAME,
            email=ADMIN_EMAIL,
            hashed_password=hashed_pw,
            role=UserRole.OWNER,
            is_active=True,
        )
        session.add(admin)
        created["admin"] = {"id": str(DEFAULT_ADMIN_ID), "username": ADMIN_USERNAME}
        print(f"[+] Created admin user: {ADMIN_USERNAME} (id={DEFAULT_ADMIN_ID})")

        if ADMIN_PASSWORD == "nexus":
            print("[!] WARNING: Using default password 'nexus'. Set NEXUS_ADMIN_PASSWORD for security.")
    else:
        print(f"[=] Admin user already exists")

    # 3. Create default workspace
    statement = select(Workspace).where(Workspace.id == DEFAULT_WORKSPACE_ID)
    if not session.exec(statement).first():
        workspace = Workspace(
            id=DEFAULT_WORKSPACE_ID,
            tenant_id=DEFAULT_TENANT_ID,
            name="Default Workspace",
            slug="default",
            filesystem_path="workspaces/default",
            is_active=True,
        )
        session.add(workspace)
        created["workspace"] = {"id": str(DEFAULT_WORKSPACE_ID), "name": "Default Workspace"}
        print(f"[+] Created workspace: Default Workspace (id={DEFAULT_WORKSPACE_ID})")
    else:
        print(f"[=] Default workspace already exists")

    # 4. Create quota for tenant
    statement = select(Quota).where(Quota.tenant_id == DEFAULT_TENANT_ID)
    if not session.exec(statement).first():
        quota = create_quota_for_plan(DEFAULT_TENANT_ID, PlanTier.PRO)
        session.add(quota)
        created["quota"] = {"tenant_id": str(DEFAULT_TENANT_ID), "plan": "PRO"}
        print(f"[+] Created quota for tenant (plan=PRO)")
    else:
        print(f"[=] Quota already exists for tenant")

    return created


def update_admin_password(session, new_password: str) -> bool:
    """
    Update the admin user's password.

    Args:
        session: Database session
        new_password: New plaintext password to hash

    Returns:
        True if updated, False if admin not found
    """
    statement = select(User).where(User.id == DEFAULT_ADMIN_ID)
    admin = session.exec(statement).first()

    if admin:
        admin.hashed_password = hash_password(new_password)
        session.add(admin)
        print(f"[+] Updated password for admin user")
        return True
    else:
        print(f"[-] Admin user not found")
        return False


def bootstrap_database() -> dict:
    """
    Full database bootstrap: init tables + create default entities.

    Returns:
        Dict with created entities info
    """
    print("=" * 60)
    print("NEXUS V12.2 IRONCLAD - Database Bootstrap")
    print("=" * 60)

    # 1. Initialize database (create tables)
    print("\n[1/2] Initializing database tables...")
    init_db()
    print("[+] Tables created/verified")

    # 2. Create default entities
    print("\n[2/2] Creating default entities...")
    with get_session() as session:
        result = create_default_entities(session)

    print("\n" + "=" * 60)
    print("Bootstrap complete!")
    print("=" * 60)

    return result


# =============================================================================
# CLI Entry Point
# =============================================================================

def main():
    """CLI entry point with argument parsing."""
    import argparse

    parser = argparse.ArgumentParser(
        description="NEXUS V12.2 Database Bootstrap",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
    python scripts/init_db.py                    # Bootstrap with defaults
    python scripts/init_db.py --reset-password   # Reset admin password

Environment Variables:
    NEXUS_ADMIN_PASSWORD  Password for admin user (default: 'nexus')
    NEXUS_ADMIN_EMAIL     Email for admin user (default: 'admin@nexus.local')
        """
    )

    parser.add_argument(
        "--reset-password",
        action="store_true",
        help="Reset admin password to NEXUS_ADMIN_PASSWORD env var value"
    )

    parser.add_argument(
        "--check",
        action="store_true",
        help="Check database state without making changes"
    )

    args = parser.parse_args()

    if args.check:
        # Check mode: just report state
        print("Checking database state...")
        init_db()
        with get_session() as session:
            tenant_exists = check_existing_tenant(session)
            admin_exists = check_existing_admin(session)
            print(f"  Tenant 'Default': {'EXISTS' if tenant_exists else 'MISSING'}")
            print(f"  Admin user: {'EXISTS' if admin_exists else 'MISSING'}")
        return

    if args.reset_password:
        # Reset password mode
        print("Resetting admin password...")
        init_db()
        with get_session() as session:
            if update_admin_password(session, ADMIN_PASSWORD):
                print("Password reset successful")
            else:
                print("Password reset failed - run bootstrap first")
                sys.exit(1)
        return

    # Default: full bootstrap
    bootstrap_database()


if __name__ == "__main__":
    main()
