"""Minimal local web UI (FastAPI). Run with `adgen web` and open http://127.0.0.1:8000."""

from __future__ import annotations

import json
import os
import threading
import traceback
import uuid
from pathlib import Path
from typing import Callable

from fastapi import FastAPI, File, Form, HTTPException, UploadFile
from fastapi.responses import FileResponse, HTMLResponse
from fastapi.staticfiles import StaticFiles
from jinja2 import Environment, FileSystemLoader

from ..avatar.library import AvatarLibrary
from ..briefs import save_scripts
from ..config import Settings
from ..cost import append_ledger, estimate_render, estimate_scripts, read_ledger
from ..models import AvatarSpec, ProductBrief, RenderOptions, ScriptSet, slugify

HERE = Path(__file__).parent
app = FastAPI(title="AdGen")
app.mount("/static", StaticFiles(directory=HERE / "static"), name="static")
templates = Environment(loader=FileSystemLoader(HERE / "templates"), autoescape=True)

JOBS: dict[str, dict] = {}
IMAGE_TYPES = {".jpg", ".jpeg", ".png", ".webp"}


def settings(offline: bool, lipsync: str | None = None) -> Settings:
    s = Settings()
    if offline:
        s = s.offline()
    return s.with_overrides(lipsync_provider=lipsync if lipsync and not offline else None)


def keys_present() -> dict[str, bool]:
    return {k: bool(os.environ.get(k)) for k in ("ANTHROPIC_API_KEY", "ELEVENLABS_API_KEY", "FAL_KEY")}


def start_job(kind: str, fn: Callable[[Callable[[str], None]], dict]) -> str:
    job_id = uuid.uuid4().hex[:12]
    job = {"id": job_id, "kind": kind, "status": "running", "log": [], "result": None, "error": None}
    JOBS[job_id] = job

    def runner():
        try:
            job["result"] = fn(job["log"].append)
            job["status"] = "done"
        except Exception as e:  # surfaced to the UI
            job["error"] = f"{type(e).__name__}: {e}"
            job["log"].append(traceback.format_exc(limit=3))
            job["status"] = "error"

    threading.Thread(target=runner, daemon=True).start()
    return job_id


def _file_url(path: Path, s: Settings) -> str:
    rel = Path(path).resolve().relative_to(s.output_dir.resolve())
    return f"/files/{rel.as_posix()}"


# ----------------------------------------------------------------------------- pages
@app.get("/", response_class=HTMLResponse)
def index():
    keys = keys_present()
    return templates.get_template("index.html").render(keys=keys, all_keys=all(keys.values()))


@app.get("/files/{path:path}")
def files(path: str):
    root = Settings().output_dir.resolve()
    target = (root / path).resolve()
    if root not in target.parents or not target.is_file():
        raise HTTPException(404)
    return FileResponse(target)


SAMPLE_DIR = HERE.parent.parent / "examples" / "sample_product"


@app.get("/api/sample")
def sample():
    data = json.loads((SAMPLE_DIR / "brief.json").read_text())
    data["image_urls"] = [f"/sample/{Path(p).name}" for p in data.pop("image_paths")]
    data["logo_url"] = f"/sample/{Path(data.pop('logo_path')).name}"
    return data


@app.get("/sample/{name}")
def sample_file(name: str):
    target = (SAMPLE_DIR / name).resolve()
    if target.parent != SAMPLE_DIR.resolve() or target.suffix.lower() not in IMAGE_TYPES or not target.exists():
        raise HTTPException(404)
    return FileResponse(target)


# ----------------------------------------------------------------------------- avatars
@app.get("/api/avatars")
def list_avatars():
    lib = AvatarLibrary(Settings().avatar_dir)
    return [
        {"id": a.id, "name": a.name, "look": a.spec.describe(), "outfit": a.spec.outfit, "setting": a.spec.setting,
         "voice_provider": a.voice_provider, "portrait": f"/avatars/{a.id}/portrait.png"}
        for a in lib.list()
    ]


@app.get("/avatars/{avatar_id}/portrait.png")
def avatar_portrait(avatar_id: str):
    lib = AvatarLibrary(Settings().avatar_dir)
    try:
        a = lib.get(avatar_id)
    except (KeyError, ValueError):
        raise HTTPException(404)
    return FileResponse(lib.portrait_path(a))


@app.post("/api/avatars")
def create_avatar(
    name: str = Form(...), age: str = Form("late 20s"), gender: str = Form("woman"), ethnicity: str = Form("unspecified"),
    setting: str = Form("bright modern apartment living room"), outfit: str = Form("casual knit sweater"),
    extra: str = Form(""), voice_description: str = Form(""), accent: str = Form("American"), language: str = Form("en"),
    offline: bool = Form(False),
):
    from ..safety import SafetyError, check_avatar_spec

    spec = AvatarSpec(age=age, gender=gender, ethnicity=ethnicity, setting=setting, outfit=outfit, extra=extra,
                      voice_description=voice_description, accent=accent, language=language)
    try:
        check_avatar_spec(spec)
    except SafetyError as e:
        raise HTTPException(400, str(e))
    s = settings(offline)

    def work(log):
        log(f"Generating portrait ({s.portrait_provider}) and voice ({s.voice_provider})...")
        av, cost = AvatarLibrary(s.avatar_dir).create(name, spec, s)
        append_ledger(s.output_dir / "cost_log.jsonl", {"kind": "avatar", "avatar": av.id, "total_usd": cost.total})
        log(f"Created {av.id} (${cost.total:.3f})")
        return {"avatar_id": av.id, "cost": cost.to_dict()}

    return {"job": start_job("avatar", work)}


# ----------------------------------------------------------------------------- briefs + scripts
@app.post("/api/brief")
async def save_brief(
    name: str = Form(...), description: str = Form(...), target_audience: str = Form(...),
    selling_points: str = Form(...), approved_claims: str = Form(""), product_url: str = Form(""),
    cta: str = Form("Shop now"), tone: str = Form("casual UGC"), length: int = Form(30),
    aspect_ratios: str = Form("9:16"), language: str = Form("en"),
    images: list[UploadFile] = File(default=[]), logo: UploadFile | None = File(default=None),
):
    s = Settings()
    brief_id = f"{slugify(name)}-{uuid.uuid4().hex[:6]}"
    folder = s.output_dir / "_briefs" / brief_id
    folder.mkdir(parents=True, exist_ok=True)
    image_paths = []
    for i, up in enumerate(images):
        if not up.filename:
            continue
        ext = Path(up.filename).suffix.lower()
        if ext not in IMAGE_TYPES:
            raise HTTPException(400, f"Unsupported image type {ext}")
        p = folder / f"image_{i}{ext}"
        p.write_bytes(await up.read())
        image_paths.append(str(p.resolve()))
    logo_path = None
    if logo is not None and logo.filename:
        ext = Path(logo.filename).suffix.lower()
        if ext not in IMAGE_TYPES:
            raise HTTPException(400, f"Unsupported logo type {ext}")
        lp = folder / f"logo{ext}"
        lp.write_bytes(await logo.read())
        logo_path = str(lp.resolve())
    try:
        brief = ProductBrief(
            name=name, description=description, target_audience=target_audience,
            selling_points=[l.strip("-• ").strip() for l in selling_points.splitlines() if l.strip()],
            approved_claims=[l.strip("-• ").strip() for l in approved_claims.splitlines() if l.strip()],
            product_url=product_url or None, cta=cta, tone=tone, length=length,
            aspect_ratios=[r for r in aspect_ratios.split(",") if r], language=language,
            image_paths=image_paths, logo_path=logo_path,
        )
    except ValueError as e:
        raise HTTPException(400, str(e))
    (folder / "brief.json").write_text(brief.model_dump_json(indent=2))
    return {"brief_id": brief_id, "brief": brief.model_dump()}


def _load_brief(brief_id: str) -> ProductBrief:
    path = Settings().output_dir / "_briefs" / slugify(brief_id) / "brief.json"
    if not path.exists():
        raise HTTPException(404, "Unknown brief")
    return ProductBrief.model_validate_json(path.read_text())


@app.post("/api/scripts/estimate")
def scripts_estimate(offline: bool = Form(False)):
    s = settings(offline)
    return estimate_scripts(s.claude_model, s.script_provider).to_dict()


@app.post("/api/scripts")
def write_scripts(brief_id: str = Form(...), offline: bool = Form(False), variants: int = Form(3)):
    brief = _load_brief(brief_id)
    s = settings(offline)

    def work(log):
        from ..script import get_script_writer

        log(f"Writing {variants} variants with {s.script_provider}...")
        ss = get_script_writer(s).write(brief, variants)
        path = save_scripts(ss, s.output_dir, brief)
        append_ledger(s.output_dir / "cost_log.jsonl", {"kind": "script", "product": brief.name, "provider": ss.provider, "total_usd": ss.cost_usd, "file": str(path)})
        log(f"Done (${ss.cost_usd:.3f}).")
        return {"scripts_file": path.name, "script_set": json.loads(ss.model_dump_json()),
                "variants": [{"variant": v.variant, "words": v.word_count, "seconds": v.est_seconds} for v in ss.variants]}

    return {"job": start_job("scripts", work)}


def _load_script_set(brief: ProductBrief, scripts_file: str) -> ScriptSet:
    path = Settings().output_dir / brief.slug / "scripts" / Path(scripts_file).name
    if not path.exists():
        raise HTTPException(404, "Unknown scripts file")
    return ScriptSet.model_validate_json(path.read_text())


@app.post("/api/render/estimate")
def render_estimate(
    brief_id: str = Form(...), scripts_file: str = Form(...), variants: str = Form(...),
    offline: bool = Form(False), lipsync: str = Form(""), music: bool = Form(True),
):
    brief = _load_brief(brief_id)
    ss = _load_script_set(brief, scripts_file)
    s = settings(offline, lipsync)
    chosen = [ss.get(v) for v in variants.split(",") if v]
    return estimate_render(brief, chosen, s.providers(), s.tts_model, music=music).to_dict()


@app.post("/api/render")
def render(
    brief_id: str = Form(...), scripts_file: str = Form(...), variants: str = Form(...), avatar_id: str = Form(...),
    offline: bool = Form(False), lipsync: str = Form(""), captions: bool = Form(True), ai_label: bool = Form(True),
    music: bool = Form(True), music_prompt: str = Form(""),
):
    brief = _load_brief(brief_id)
    ss = _load_script_set(brief, scripts_file)
    s = settings(offline, lipsync)
    lib = AvatarLibrary(s.avatar_dir)
    try:
        avatar = lib.get(avatar_id)
    except KeyError as e:
        raise HTTPException(404, str(e))
    chosen = [ss.get(v) for v in variants.split(",") if v]
    opts = RenderOptions(captions=captions, ai_label=ai_label, music=music, music_prompt=music_prompt)

    def work(log):
        from ..pipeline import Renderer

        results = Renderer(s, opts, progress=log).render(brief, chosen, avatar, lib, ss)
        return {
            "ads": [
                {
                    "variant": r.variant,
                    "duration": r.duration,
                    "cost": r.cost.total,
                    "warnings": r.warnings,
                    "thumbnail": _file_url(r.thumbnail, s),
                    "videos": {ratio: _file_url(v, s) for ratio, v in r.videos.items()},
                    "posters": {
                        ratio: _file_url(r.thumbnail if v == r.videos[brief.aspect_ratios[0]] else r.folder / f"thumbnail_{ratio.replace(':', 'x')}.jpg", s)
                        for ratio, v in r.videos.items()
                    },
                    "script": _file_url(r.folder / "script.txt", s),
                    "folder": str(r.folder),
                }
                for r in results
            ]
        }

    return {"job": start_job("render", work)}


@app.get("/api/jobs/{job_id}")
def job_status(job_id: str):
    job = JOBS.get(job_id)
    if not job:
        raise HTTPException(404)
    return job


@app.get("/api/costs")
def costs():
    entries = read_ledger(Settings().output_dir / "cost_log.jsonl")
    return {"total_usd": round(sum(e.get("total_usd", 0) for e in entries), 4), "entries": entries[-50:]}
