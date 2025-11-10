"""
Test Migration Script

This script helps migrate from old unittest-based tests to new pytest-based tests.
It renames old files to .old and activates new refactored tests.

Usage:
    python migrate_tests.py --backup    # Create backups of old tests
    python migrate_tests.py --activate  # Activate refactored tests
    python migrate_tests.py --rollback  # Restore original tests
"""

import sys
import shutil
from pathlib import Path

# Mapping of old test files to new refactored files
MIGRATION_MAP = {
    # Core pipeline tests
    'test_watchtower_pipeline.py': 'test_watchtower_pipeline_refactored.py',

    # Handler tests (consolidated)
    'test_telegram_handler.py': 'test_handlers_refactored.py',
    'test_discord_handler.py': 'test_handlers_refactored.py',  # Same target

    # Routing tests
    'test_message_router.py': 'test_routing_refactored.py',

    # Simple unit tests (consolidated)
    'test_message_data.py': 'test_simple_units_refactored.py',
    'test_message_queue.py': 'test_simple_units_refactored.py',  # Same target
    'test_ocr_handler.py': 'test_simple_units_refactored.py',    # Same target
    'test_metrics.py': 'test_simple_units_refactored.py',        # Same target
}

def backup_tests():
    """Rename old test files to .old"""
    print("Creating backups of old test files...")
    tests_dir = Path(__file__).parent

    for old_file in MIGRATION_MAP.keys():
        old_path = tests_dir / old_file
        if old_path.exists():
            backup_path = old_path.with_suffix('.py.old')
            print(f"  Backing up: {old_file} -> {backup_path.name}")
            shutil.copy2(old_path, backup_path)

    print("✓ Backups created!")

def activate_refactored():
    """Activate refactored tests by renaming them"""
    print("Activating refactored tests...")
    tests_dir = Path(__file__).parent

    # First, rename old files
    for old_file in MIGRATION_MAP.keys():
        old_path = tests_dir / old_file
        if old_path.exists() and not (old_path.parent / f"{old_file}.old").exists():
            temp_path = old_path.with_suffix('.py.old')
            print(f"  Renaming old: {old_file} -> {temp_path.name}")
            old_path.rename(temp_path)

    # Then, activate refactored files
    activated = set()
    for old_file, new_file in MIGRATION_MAP.items():
        if new_file in activated:
            continue

        new_path = tests_dir / new_file
        if new_path.exists():
            # Remove _refactored suffix
            final_name = new_file.replace('_refactored', '')
            final_path = tests_dir / final_name

            if not final_path.exists():
                print(f"  Activating: {new_file} -> {final_name}")
                shutil.copy2(new_path, final_path)
                activated.add(new_file)

    print("✓ Refactored tests activated!")

def rollback():
    """Restore original tests from backups"""
    print("Rolling back to original tests...")
    tests_dir = Path(__file__).parent

    for old_file in MIGRATION_MAP.keys():
        backup_path = tests_dir / f"{old_file}.old"
        if backup_path.exists():
            original_path = tests_dir / old_file
            print(f"  Restoring: {backup_path.name} -> {old_file}")
            shutil.copy2(backup_path, original_path)

    print("✓ Original tests restored!")

def show_stats():
    """Show statistics about test migration"""
    tests_dir = Path(__file__).parent

    print("\n=== Test Migration Statistics ===")

    # Count lines in old tests
    old_lines = 0
    for old_file in MIGRATION_MAP.keys():
        old_path = tests_dir / f"{old_file}.old"
        if not old_path.exists():
            old_path = tests_dir / old_file
        if old_path.exists():
            with open(old_path) as f:
                old_lines += len(f.readlines())

    # Count lines in new tests
    new_lines = 0
    counted = set()
    for new_file in set(MIGRATION_MAP.values()):
        if new_file in counted:
            continue
        new_path = tests_dir / new_file
        if new_path.exists():
            with open(new_path) as f:
                new_lines += len(f.readlines())
            counted.add(new_file)

    # Add conftest.py
    conftest_path = tests_dir / 'conftest.py'
    if conftest_path.exists():
        with open(conftest_path) as f:
            conftest_lines = len(f.readlines())
        new_lines += conftest_lines
        print(f"conftest.py: {conftest_lines} lines (shared fixtures)")

    print(f"\nOld tests: {old_lines:,} lines")
    print(f"New tests: {new_lines:,} lines")

    if old_lines > 0:
        reduction = ((old_lines - new_lines) / old_lines) * 100
        print(f"Reduction: {reduction:.1f}%")
        print(f"Lines saved: {old_lines - new_lines:,}")

def main():
    if len(sys.argv) < 2:
        print(__doc__)
        return

    command = sys.argv[1]

    if command == '--backup':
        backup_tests()
    elif command == '--activate':
        activate_refactored()
        show_stats()
    elif command == '--rollback':
        rollback()
    elif command == '--stats':
        show_stats()
    else:
        print(f"Unknown command: {command}")
        print(__doc__)

if __name__ == '__main__':
    main()
