from pathlib import Path

import pytest

FIXTURES_DIR = Path(__file__).parent / "fixtures"


@pytest.fixture
def staff_configs_dir():
    return FIXTURES_DIR / "staff_configs"


@pytest.fixture
def dept_req_file():
    return FIXTURES_DIR / "department.txt"


@pytest.fixture
def law_file():
    return FIXTURES_DIR / "law.txt"
