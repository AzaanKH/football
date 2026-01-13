#!/usr/bin/env python3
"""
Test Runner for Fantasy Football Data Pipeline

This script provides convenient commands for running different test suites.

Usage:
    python run_tests.py              # Run all unit tests (fast, no external deps)
    python run_tests.py unit         # Run unit tests only
    python run_tests.py integration  # Run integration tests (needs internet)
    python run_tests.py e2e          # Run end-to-end tests (needs Docker + internet)
    python run_tests.py all          # Run all tests
    python run_tests.py coverage     # Run unit tests with coverage report

Prerequisites:
    1. Install test dependencies: pip install -r requirements_test.txt
    2. For e2e tests: docker-compose up -d
"""

import sys
import subprocess
import os

# Change to backend directory
os.chdir(os.path.dirname(os.path.abspath(__file__)))


def run_command(cmd: list, description: str):
    """Run a command and print results."""
    print(f"\n{'='*60}")
    print(f"Running: {description}")
    print(f"Command: {' '.join(cmd)}")
    print('='*60 + "\n")

    result = subprocess.run(cmd, shell=True if os.name == 'nt' else False)
    return result.returncode


def check_docker():
    """Check if Docker database is running."""
    try:
        import psycopg2
        conn = psycopg2.connect(
            'postgresql://postgres:postgres@localhost:5432/football_dev',
            connect_timeout=3
        )
        conn.close()
        return True
    except Exception:
        return False


def main():
    """Main entry point."""
    if len(sys.argv) < 2:
        command = 'unit'
    else:
        command = sys.argv[1].lower()

    commands = {
        'unit': {
            'cmd': ['pytest', 'tests/', '-m', 'unit', '-v', '--tb=short'],
            'desc': 'Unit Tests (mocked dependencies)',
            'requires_docker': False
        },
        'integration': {
            'cmd': ['pytest', 'tests/test_integration.py', '-m', 'integration', '-v', '--tb=short'],
            'desc': 'Integration Tests (real API calls)',
            'requires_docker': False
        },
        'e2e': {
            'cmd': ['pytest', 'tests/test_e2e.py', '-m', 'e2e', '-v', '--tb=short'],
            'desc': 'End-to-End Tests (real API + database)',
            'requires_docker': True
        },
        'all': {
            'cmd': ['pytest', 'tests/', '-v', '--tb=short'],
            'desc': 'All Tests',
            'requires_docker': True
        },
        'coverage': {
            'cmd': ['pytest', 'tests/', '-m', 'unit', '-v',
                   '--cov=data_pipeline', '--cov-report=html', '--cov-report=term'],
            'desc': 'Unit Tests with Coverage',
            'requires_docker': False
        },
        'fast': {
            'cmd': ['pytest', 'tests/', '-m', 'unit', '-v', '-x', '--tb=short'],
            'desc': 'Unit Tests (stop on first failure)',
            'requires_docker': False
        }
    }

    if command == 'help':
        print(__doc__)
        print("\nAvailable commands:")
        for name, info in commands.items():
            docker_note = " (requires Docker)" if info['requires_docker'] else ""
            print(f"  {name:12} - {info['desc']}{docker_note}")
        return 0

    if command not in commands:
        print(f"Unknown command: {command}")
        print("Use 'python run_tests.py help' for available commands")
        return 1

    config = commands[command]

    # Check Docker if required
    if config['requires_docker'] and not check_docker():
        print("\n" + "!"*60)
        print("ERROR: Docker database is not running!")
        print("Start it with: docker-compose up -d")
        print("!"*60 + "\n")
        return 1

    return run_command(config['cmd'], config['desc'])


if __name__ == '__main__':
    sys.exit(main())
