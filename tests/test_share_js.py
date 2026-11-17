"""Runs the JavaScript share tests (tests/share.test.mjs) with Node's built-in test runner."""
import shutil
import subprocess
from pathlib import Path

import pytest


@pytest.mark.skipif(not shutil.which("node"), reason="Node.js not installed")
def test_share_js():
    here = Path(__file__).parent
    r = subprocess.run(["node", "--test", str(here / "share.test.mjs")], capture_output=True, text=True, timeout=120)
    assert r.returncode == 0, r.stdout[-3000:] + r.stderr[-2000:]
