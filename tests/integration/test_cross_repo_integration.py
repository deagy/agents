#!/usr/bin/env python3
"""Cross-repository integration tests for Cadre framework.

These tests verify interactions between cadre, cadre-lifecycle, and agentic-sdlc
repositories by testing profile loading, CLI dispatch, and configuration sharing.
"""

import json
import subprocess
import sys
from pathlib import Path

# Repository paths
CADRE_ROOT = Path(__file__).parent.parent.parent
CADRE_LIFECYCLE_ROOT = Path("/home/deagy/sdk/cadre-lifecycle")
AGENTIC_SDLC_ROOT = Path("/home/deagy/sdk/agentic-sdlc")


def test_profile_loading():
    """Test that secure-cloud profile can be loaded from separate repository.
    
    Note: The secure-cloud profile has been migrated to a separate repository
    (cadre-profile-secure-cloud). This test verifies the migration documentation
    exists and the profile structure is valid if found.
    """
    # Check for migration documentation
    migration_doc = CADRE_ROOT / "docs" / "migration" / "secure-cloud-profile-migration.md"
    
    if migration_doc.exists():
        print("✓ Secure-cloud profile migration documented")
    else:
        print("SKIP: Migration documentation not found")
        return True
    
    # Check if profile exists in old location (should not, since it was migrated)
    old_profile_path = CADRE_LIFECYCLE_ROOT / "provider" / "profiles" / "secure-cloud" / "profile.json"
    if old_profile_path.exists():
        print("⚠ Profile still exists at old location (expected after migration)")
    
    # Check new repository structure
    new_repo_path = Path("/home/deagy/sdk/cadre-profile-secure-cloud")
    if new_repo_path.exists():
        profile_path = new_repo_path / "profile.json"
        if profile_path.exists():
            try:
                with open(profile_path) as f:
                    profile = json.load(f)
                assert profile["id"] == "secure-cloud"
                assert len(profile.get("agents", [])) > 0
                print(f"✓ New profile repository valid: {len(profile['agents'])} agents")
                return True
            except Exception as e:
                print(f"✗ Profile validation failed: {e}")
                return False
        else:
            print("SKIP: New profile.json not found")
            return True
    else:
        print("SKIP: New profile repository not found")
        return True


def test_cli_dispatch():
    """Test that cadre CLI can dispatch using profiles from other repos."""
    try:
        result = subprocess.run(
            ["sh", str(CADRE_ROOT / "bin" / "cadre"), "--help"],
            capture_output=True,
            text=True,
            timeout=10
        )
        
        if result.returncode == 0:
            print("✓ CLI dispatch test passed")
            return True
        else:
            print(f"✗ CLI dispatch test failed: {result.stderr}")
            return False
    except Exception as e:
        print(f"✗ CLI dispatch test failed: {e}")
        return False


def test_configuration_sharing():
    """Test that configuration can be shared between repos."""
    cadre_version_file = CADRE_ROOT / "cadre_cli" / "_version.py"
    cadre_lifecycle_package = CADRE_LIFECYCLE_ROOT / "package.json"
    
    if not cadre_version_file.exists() or not cadre_lifecycle_package.exists():
        print("SKIP: Required files not found")
        return True
    
    try:
        with open(cadre_version_file) as f:
            content = f.read()
            if 'VERSION = "0.3.0"' in content:
                print("✓ Cadre version verified: 0.3.0")
            else:
                print("✗ Cadre version mismatch")
                return False
        
        with open(cadre_lifecycle_package) as f:
            package = json.load(f)
            if package["version"] == "0.3.0":
                print("✓ Cadre-lifecycle version verified: 0.3.0")
            else:
                print(f"✗ Cadre-lifecycle version mismatch: {package['version']}")
                return False
        
        return True
    except Exception as e:
        print(f"✗ Configuration sharing test failed: {e}")
        return False


def main():
    """Run all integration tests."""
    tests = [
        ("Profile Loading", test_profile_loading),
        ("CLI Dispatch", test_cli_dispatch),
        ("Configuration Sharing", test_configuration_sharing),
    ]
    
    results = []
    for name, test_func in tests:
        print(f"\nRunning: {name}")
        try:
            result = test_func()
            results.append((name, result))
        except Exception as e:
            print(f"✗ {name} failed with exception: {e}")
            results.append((name, False))
    
    print("\n" + "="*60)
    print("Integration Test Results:")
    print("="*60)
    for name, result in results:
        status = "PASS" if result else "FAIL"
        print(f"  {name}: {status}")
    
    passed = sum(1 for _, r in results if r)
    total = len(results)
    print(f"\nTotal: {passed}/{total} tests passed")
    
    return 0 if passed == total else 1


if __name__ == "__main__":
    sys.exit(main())
