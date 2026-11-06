from pathlib import Path

import pytest

from cuas.config import SiteConfig, load_site

ROOT = Path(__file__).resolve().parents[1]


@pytest.fixture
def config_dir() -> Path:
    return ROOT / "config"


@pytest.fixture
def site(config_dir: Path) -> SiteConfig:
    return load_site(config_dir)
