import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))


@pytest.fixture()
def home(tmp_path, monkeypatch):
    """A fresh Clip Studio data folder for each test."""
    from clipstudio import db
    monkeypatch.setenv("CLIPSTUDIO_HOME", str(tmp_path / "home"))
    db.set_home(tmp_path / "home")
    db.conn()
    yield tmp_path / "home"
    db.set_home(tmp_path / "unused")
