#!/usr/bin/env python3
"""
Test runner script for the stock analysis platform.

Usage:
    python scripts/run_tests.py unit       # Fast unit tests only (no API calls)
    python scripts/run_tests.py integration # Slow integration tests (real API calls) 
    python scripts/run_tests.py all        # All tests
"""

import sys
import subprocess
from pathlib import Path

def run_tests(test_type):
    """Run tests based on type."""
    base_cmd = ["uv", "run", "pytest", "-v"]
    
    if test_type == "unit":
        # Run only unit tests (exclude integration)
        cmd = base_cmd + ["-m", "not integration"]
        print("🚀 Running UNIT TESTS (fast, no API calls)...")
        
    elif test_type == "integration":
        # Run only integration tests
        cmd = base_cmd + ["-m", "integration"]
        print("🐌 Running INTEGRATION TESTS (slow, real API calls)...")
        print("⚠️  Make sure OPENAI_API_KEY is set!")
        
    elif test_type == "all":
        # Run all tests
        cmd = base_cmd
        print("🎯 Running ALL TESTS (unit + integration)...")
        
    else:
        print(f"❌ Unknown test type: {test_type}")
        print("Usage: python scripts/run_tests.py [unit|integration|all]")
        return 1
    
    # Run tests
    try:
        result = subprocess.run(cmd, cwd=Path(__file__).parent.parent)
        return result.returncode
    except KeyboardInterrupt:
        print("\n❌ Tests interrupted by user")
        return 1
    except Exception as e:
        print(f"❌ Error running tests: {e}")
        return 1

if __name__ == "__main__":
    if len(sys.argv) != 2:
        print("Usage: python scripts/run_tests.py [unit|integration|all]")
        sys.exit(1)
        
    test_type = sys.argv[1]
    exit_code = run_tests(test_type)
    sys.exit(exit_code)