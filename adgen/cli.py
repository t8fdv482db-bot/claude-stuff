"""Command-line interface: `adgen --help`."""

from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Optional

import typer
from rich.console import Console
from rich.table import Table

from .avatar.library import AvatarLibrary
from .briefs import latest_scripts, load_brief, load_scripts, save_scripts
from .config import ConfigError, Settings
from .cost import CostReport, append_ledger, estimate_render, estimate_scripts, read_ledger
from .models import AdScript, AvatarSpec, RenderOptions, ScriptSet
from .safety import SafetyError

app = typer.Typer(help="AI video ad generator: product brief in, finished ads out.", no_args_is_help=True)
avatar_app = typer.Typer(help="Manage the library of reusable synthetic presenters.", no_args_is_help=True)
app.add_typer(avatar_app, name="avatar")
console = Console()

OFFLINE = typer.Option(False, "--offline", help="Use free local mock providers (no keys, no network).")
YES = typer.Option(False, "--yes", "-y", help="Skip the cost confirmation prompt.")


def _settings(offline: bool, **overrides) -> Settings:
    s = Settings()
    if offline:
        s = s.offline()
    return s.with_overrides(**overrides)


def _show_cost(title: str, report: CostReport) -> None:
    t = Table(title=title, show_lines=False)
    for col in ("stage", "provider", "detail"):
        t.add_column(col)
    t.add_column("USD", justify="right")
    for l in report.lines:
        t.add_row(l.stage, l.provider, l.detail, f"${l.usd:.3f}")
    t.add_row("", "", "[bold]total[/bold]", f"[bold]${report.total:.2f}[/bold]")
    console.print(t)


def _confirm(report: CostReport, yes: bool) -> None:
    if yes or report.total == 0:
        return
    if not typer.confirm(f"Proceed? Estimated spend ${report.total:.2f}", default=True):
        raise typer.Abort()


def _show_scripts(ss: ScriptSet) -> None:
    for v in ss.variants:
        t = Table(title=f"Variant {v.variant}: {v.angle}  ({v.word_count} words, ~{v.est_seconds}s)", show_header=True)
        t.add_column("role")
        t.add_column("shot")
        t.add_column("read")
        t.add_column("line")
        for s in v.segments:
            t.add_row(s.role, s.visual, s.delivery, s.text)
        t.add_row("end card", "", "", v.on_screen_cta)
        console.print(t)


def _run(fn):
    try:
        return fn()
    except (ConfigError, SafetyError, FileNotFoundError, KeyError, ValueError, RuntimeError) as e:
        console.print(f"[red]Error:[/red] {e}")
        raise typer.Exit(1)


@app.callback()
def main(verbose: bool = typer.Option(False, "--verbose", "-v")):
    logging.basicConfig(level=logging.INFO if verbose else logging.WARNING, format="%(message)s")


# --------------------------------------------------------------------------- scripts
@app.command()
def script(
    brief: Path = typer.Argument(..., help="Product brief JSON"),
    variants: int = typer.Option(3, "--variants", "-n", min=1, max=5),
    length: Optional[int] = typer.Option(None, help="Override ad length (15, 20, 30)"),
    tone: Optional[str] = typer.Option(None, help="Override tone"),
    offline: bool = OFFLINE,
    yes: bool = YES,
):
    """Write N script variants (hook -> problem -> solution -> CTA) for A/B testing."""

    def go():
        s = _settings(offline)
        b = load_brief(brief, length=length, tone=tone)
        est = estimate_scripts(s.claude_model, s.script_provider)
        _show_cost("Script estimate", est)
        _confirm(est, yes)
        from .script import get_script_writer

        with console.status("Writing scripts..."):
            ss = get_script_writer(s).write(b, variants)
        path = save_scripts(ss, s.output_dir, b)
        append_ledger(s.output_dir / "cost_log.jsonl", {"kind": "script", "product": b.name, "provider": ss.provider, "total_usd": ss.cost_usd, "file": str(path)})
        _show_scripts(ss)
        console.print(f"Saved [bold]{path}[/bold]  (actual cost ${ss.cost_usd:.3f})")

    _run(go)


# --------------------------------------------------------------------------- avatars
@avatar_app.command("create")
def avatar_create(
    name: str = typer.Argument(..., help="Display name for the presenter, e.g. 'Maya'"),
    age: str = typer.Option("late 20s"),
    gender: str = typer.Option("woman"),
    ethnicity: str = typer.Option("unspecified"),
    setting: str = typer.Option("bright modern apartment living room"),
    outfit: str = typer.Option("casual knit sweater"),
    extra: str = typer.Option("", help="Extra look details (hair, expression). No real people."),
    voice: str = typer.Option("", help="Voice description; defaults to one matched to the avatar."),
    accent: str = typer.Option("American"),
    language: str = typer.Option("en"),
    offline: bool = OFFLINE,
    yes: bool = YES,
):
    """Generate a new fully synthetic presenter (portrait + matched voice) and save it."""

    def go():
        s = _settings(offline)
        spec = AvatarSpec(age=age, gender=gender, ethnicity=ethnicity, setting=setting, outfit=outfit, extra=extra, voice_description=voice, accent=accent, language=language)
        from .cost import portrait_cost, voice_design_cost
        from .safety import check_avatar_spec

        check_avatar_spec(spec)
        est = CostReport()
        est.add("avatar", s.portrait_provider, "portrait image", portrait_cost(s.portrait_provider))
        est.add("voice", s.voice_provider, "voice design", voice_design_cost(s.voice_provider))
        _show_cost("Avatar estimate", est)
        _confirm(est, yes)
        lib = AvatarLibrary(s.avatar_dir)
        with console.status("Generating presenter..."):
            av, cost = lib.create(name, spec, s)
        append_ledger(s.output_dir / "cost_log.jsonl", {"kind": "avatar", "avatar": av.id, "total_usd": cost.total})
        console.print(f"Created avatar [bold]{av.id}[/bold] -> {lib.portrait_path(av)}  (cost ${cost.total:.3f})")

    _run(go)


@avatar_app.command("list")
def avatar_list():
    """List saved presenters."""
    lib = AvatarLibrary(Settings().avatar_dir)
    t = Table(title=f"Avatars in {lib.root}")
    for col in ("id", "name", "look", "outfit", "voice", "created"):
        t.add_column(col)
    for a in lib.list():
        t.add_row(a.id, a.name, a.spec.describe(), a.spec.outfit, f"{a.voice_provider}:{a.voice_id}", a.created_at[:10])
    console.print(t)


@avatar_app.command("show")
def avatar_show(avatar_id: str):
    """Show a presenter's full spec."""
    lib = AvatarLibrary(Settings().avatar_dir)
    _run(lambda: console.print_json(lib.get(avatar_id).model_dump_json()))


@avatar_app.command("delete")
def avatar_delete(avatar_id: str, yes: bool = YES):
    """Delete a presenter from the library."""
    lib = AvatarLibrary(Settings().avatar_dir)
    if not yes and not typer.confirm(f"Delete avatar {avatar_id}?"):
        raise typer.Abort()
    _run(lambda: lib.delete(avatar_id))
    console.print(f"Deleted {avatar_id}")


# --------------------------------------------------------------------------- voice test
@app.command()
def voice(
    brief: Path = typer.Argument(..., help="Product brief JSON"),
    avatar: str = typer.Option(..., "--avatar", "-a"),
    scripts: Optional[Path] = typer.Option(None, help="Script set JSON (default: latest for this product)"),
    variant: str = typer.Option("A"),
    offline: bool = OFFLINE,
):
    """Synthesise just the voice-over for one variant (to audition the read)."""

    def go():
        s = _settings(offline)
        b = load_brief(brief)
        ss = load_scripts(scripts or latest_scripts(s.output_dir, b) or _no_scripts())
        sc = ss.get(variant)
        av = AvatarLibrary(s.avatar_dir).get(avatar)
        from .cost import tts_cost
        from .voice import fit_to_length, get_voice_provider

        out = s.output_dir / b.slug / "voice_tests" / f"{av.id}_{sc.variant}"
        with console.status("Synthesising..."):
            raw = get_voice_provider(s).synthesize(sc, av.voice_id, b.language, out)
            track = fit_to_length(raw, b.length - 1.8, out)
        usd = tts_cost(s.voice_provider, s.tts_model, raw.characters)
        append_ledger(s.output_dir / "cost_log.jsonl", {"kind": "voice_test", "product": b.name, "total_usd": usd})
        console.print(f"{track.audio_path}: {track.duration:.1f}s, {len(track.words)} words, tempo {track.tempo}x, cost ${usd:.3f}")

    _run(go)


def _no_scripts():
    raise FileNotFoundError("No saved scripts for this product; run `adgen script BRIEF` first or pass --scripts.")


# --------------------------------------------------------------------------- render
def _pick(ss: ScriptSet, variants: str | None) -> list[AdScript]:
    if not variants:
        return ss.variants
    return [ss.get(v.strip()) for v in variants.split(",") if v.strip()]


@app.command()
def estimate(
    brief: Path = typer.Argument(...),
    scripts: Optional[Path] = typer.Option(None),
    variants: Optional[str] = typer.Option(None, help="Comma list, e.g. A,C (default: all)"),
    offline: bool = OFFLINE,
    lipsync: Optional[str] = typer.Option(None, help="Override lip-sync provider"),
):
    """Show the cost estimate for rendering, without spending anything."""

    def go():
        s = _settings(offline, lipsync_provider=lipsync)
        b = load_brief(brief)
        path = scripts or latest_scripts(s.output_dir, b)
        ss = load_scripts(path) if path else None
        if ss is None:
            from .script.mock import MockScriptWriter

            ss = MockScriptWriter().write(b)  # placeholder lengths for an estimate
            _show_cost("Script estimate", estimate_scripts(s.claude_model, s.script_provider))
        _show_cost("Render estimate", estimate_render(b, _pick(ss, variants), s.providers(), s.tts_model))

    _run(go)


@app.command()
def render(
    brief: Path = typer.Argument(..., help="Product brief JSON"),
    avatar: str = typer.Option(..., "--avatar", "-a", help="Avatar id from `adgen avatar list`"),
    scripts: Optional[Path] = typer.Option(None, help="Script set JSON (default: latest; writes new scripts if none)"),
    variants: Optional[str] = typer.Option(None, help="Comma list, e.g. A,C (default: all)"),
    length: Optional[int] = typer.Option(None),
    ratios: Optional[str] = typer.Option(None, help="Comma list of 9:16,1:1,16:9"),
    captions: bool = typer.Option(True, "--captions/--no-captions"),
    ai_label: bool = typer.Option(True, "--ai-label/--no-ai-label", help="Small 'AI-generated' disclosure label"),
    music: bool = typer.Option(True, "--music/--no-music"),
    music_prompt: str = typer.Option("", help="Custom music prompt"),
    lipsync: Optional[str] = typer.Option(None, help="kling_avatar_v2_pro | kling_avatar_v2_standard | omnihuman_v15 | mock"),
    offline: bool = OFFLINE,
    yes: bool = YES,
):
    """Render finished ads: voice, lip-synced presenter, B-roll, captions, music, end card."""

    def go():
        s = _settings(offline, lipsync_provider=lipsync)
        b = load_brief(brief, length=length, aspect_ratios=ratios.split(",") if ratios else None)
        lib = AvatarLibrary(s.avatar_dir)
        av = lib.get(avatar)
        path = scripts or latest_scripts(s.output_dir, b)
        if path and length is None:
            ss = load_scripts(path)
        else:
            est = estimate_scripts(s.claude_model, s.script_provider)
            _show_cost("Script estimate", est)
            _confirm(est, yes)
            from .script import get_script_writer

            with console.status("Writing scripts..."):
                ss = get_script_writer(s).write(b)
            path = save_scripts(ss, s.output_dir, b)
            append_ledger(s.output_dir / "cost_log.jsonl", {"kind": "script", "product": b.name, "provider": ss.provider, "total_usd": ss.cost_usd, "file": str(path)})
        chosen = _pick(ss, variants)
        _show_scripts(ScriptSet(product=ss.product, provider=ss.provider, variants=chosen))
        opts = RenderOptions(captions=captions, ai_label=ai_label, music=music, music_prompt=music_prompt)
        est = estimate_render(b, chosen, s.providers(), s.tts_model, music=music)
        _show_cost("Render estimate", est)
        _confirm(est, yes)
        from .pipeline import Renderer

        results = Renderer(s, opts, progress=lambda m: console.print(f"  [dim]{m}[/dim]")).render(b, chosen, av, lib, ss)
        t = Table(title="Finished ads")
        for col in ("variant", "length", "files", "cost", "notes"):
            t.add_column(col)
        for r in results:
            t.add_row(r.variant, f"{r.duration:.1f}s", "\n".join(str(v) for v in r.videos.values()), f"${r.cost.total:.3f}", "\n".join(r.warnings))
        console.print(t)
        job = json.loads((results[0].folder.parent / "job.json").read_text())
        console.print(f"Total actual spend: [bold]${job['total_usd']:.3f}[/bold]  (logged to {s.output_dir / 'cost_log.jsonl'})")

    _run(go)


@app.command()
def costs():
    """Summarise the cost log."""
    s = Settings()
    entries = read_ledger(s.output_dir / "cost_log.jsonl")
    t = Table(title=f"Cost log ({len(entries)} entries)")
    for col in ("when", "kind", "product / avatar", "USD"):
        t.add_column(col)
    total = 0.0
    for e in entries:
        total += e.get("total_usd", 0.0)
        t.add_row(e["logged_at"][:19], e["kind"], e.get("product") or e.get("avatar", ""), f"${e.get('total_usd', 0):.3f}")
    t.add_row("", "", "[bold]total[/bold]", f"[bold]${total:.2f}[/bold]")
    console.print(t)


@app.command()
def demo(length: int = typer.Option(15)):
    """Fully offline end-to-end run on the bundled sample product (free)."""
    root = Path(__file__).resolve().parent.parent
    brief_path = root / "examples/sample_product/brief.json"
    s = _settings(True)
    lib = AvatarLibrary(s.avatar_dir)
    try:
        av = lib.get("demo-host")
    except KeyError:
        av, _ = lib.create("Demo Host", AvatarSpec(), s)
    b = load_brief(brief_path, length=length)
    from .pipeline import Renderer
    from .script.mock import MockScriptWriter

    ss = MockScriptWriter().write(b)
    results = Renderer(s, progress=lambda m: console.print(f"  [dim]{m}[/dim]")).render(b, ss.variants[:1], av, lib, ss)
    for r in results:
        for ratio, v in r.videos.items():
            console.print(f"{ratio}: {v}")


@app.command()
def web(host: str = "127.0.0.1", port: int = 8000):
    """Start the web UI."""
    import uvicorn

    uvicorn.run("adgen.web.app:app", host=host, port=port)


if __name__ == "__main__":
    app()
