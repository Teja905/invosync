#!/usr/bin/env python3

import sys
sys.path.insert(0, '.')

# Run the tests
import pytest

if __name__ == "__main__":
    sys.exit(pytest.main([
        "test_tally_edge_cases.py::TestJournalServiceVoucherIntegration",
        "-v",
        "--tb=short"
    ]))