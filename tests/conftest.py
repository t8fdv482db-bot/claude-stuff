import json
from pathlib import Path

import pytest

from adgen.models import ProductBrief

ROOT = Path(__file__).resolve().parent.parent


@pytest.fixture
def brief() -> ProductBrief:
    data = json.loads((ROOT / "examples/sample_product/brief.json").read_text())
    data["image_paths"] = [str(ROOT / p) for p in data["image_paths"]]
    data["logo_path"] = str(ROOT / data["logo_path"])
    return ProductBrief(**data)
