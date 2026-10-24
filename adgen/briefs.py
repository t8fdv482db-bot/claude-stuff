"""Loading product briefs and saved script sets from disk."""

from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path

from .models import ProductBrief, ScriptSet


def _resolve(p: str, base: Path) -> str:
    path = Path(p).expanduser()
    if path.is_absolute() or path.exists():
        return str(path.resolve())
    candidate = base / path
    return str(candidate.resolve()) if candidate.exists() else str(path)


def load_brief(path: str | Path, **overrides) -> ProductBrief:
    path = Path(path)
    data = json.loads(path.read_text())
    base = path.parent
    data["image_paths"] = [_resolve(p, base) for p in data.get("image_paths", [])]
    if data.get("logo_path"):
        data["logo_path"] = _resolve(data["logo_path"], base)
    data.update({k: v for k, v in overrides.items() if v is not None})
    brief = ProductBrief(**data)
    missing = [p for p in brief.image_paths + ([brief.logo_path] if brief.logo_path else []) if not Path(p).exists()]
    if missing:
        raise FileNotFoundError(f"Brief references missing files: {missing}")
    return brief


def save_scripts(script_set: ScriptSet, output_dir: Path, brief: ProductBrief) -> Path:
    folder = output_dir / brief.slug / "scripts"
    folder.mkdir(parents=True, exist_ok=True)
    path = folder / f"{datetime.now().strftime('%Y%m%d-%H%M%S')}.json"
    path.write_text(script_set.model_dump_json(indent=2))
    return path


def load_scripts(path: str | Path) -> ScriptSet:
    return ScriptSet.model_validate_json(Path(path).read_text())


def latest_scripts(output_dir: Path, brief: ProductBrief) -> Path | None:
    files = sorted((output_dir / brief.slug / "scripts").glob("*.json"))
    return files[-1] if files else None
