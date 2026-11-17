"""Routes for multi-account posting: accounts, board, pipeline, calendar, analytics."""
from __future__ import annotations

import json

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import HTMLResponse

from . import accounts as acc
from . import db

router = APIRouter()


def _page(request: Request, name: str, **ctx) -> HTMLResponse:
    from .app import page
    return page(request, name, **ctx)


async def _json(request: Request) -> dict:
    try:
        return json.loads(await request.body() or b"{}")
    except ValueError as e:
        raise HTTPException(400, "Invalid JSON") from e


def _rule(fn, *args, **kw):
    try:
        return fn(*args, **kw)
    except acc.RuleError as e:
        raise HTTPException(409, str(e)) from e


def _common() -> dict:
    return {"platforms": acc.PLATFORMS, "statuses": acc.STATUS_LABELS,
            "streamers": db.q("SELECT id, name FROM streamers ORDER BY name")}


# ---------------------------------------------------------------- pages
@router.get("/board", response_class=HTMLResponse)
def board_page(request: Request):
    return _page(request, "board.html", default_limit=int(db.setting("default_daily_limit") or 3), **_common())


@router.get("/pipeline", response_class=HTMLResponse)
def pipeline_page(request: Request):
    return _page(request, "pipeline.html", accounts=acc.list_accounts(), **_common())


@router.get("/calendar", response_class=HTMLResponse)
def calendar_page(request: Request, week: int = 0, account: int | None = None):
    return _page(request, "calendar.html", cal=acc.week(week, account), account_filter=account,
                 all_accounts=acc.list_accounts(), **_common())


@router.get("/analytics", response_class=HTMLResponse)
def analytics_page(request: Request):
    data = acc.analytics()
    return _page(request, "analytics.html", data=data, data_json=json.dumps(data, default=str), **_common())


# ---------------------------------------------------------------- accounts API
@router.get("/api/accounts")
def api_accounts(archived: bool = False):
    return {"accounts": acc.list_accounts(include_archived=archived)}


@router.post("/api/accounts")
async def api_create_account(request: Request):
    return _rule(acc.create_account, await _json(request))


@router.put("/api/accounts/{aid}")
async def api_update_account(aid: int, request: Request):
    cur = db.get("accounts", aid)
    if not cur:
        raise HTTPException(404, "No such account")
    vals = _rule(acc.validate_account, await _json(request), cur)
    if "handle" in vals or "platform" in vals:
        p, h = vals.get("platform", cur["platform"]), vals.get("handle", cur["handle"])
        if db.q1("SELECT id FROM accounts WHERE platform=? AND lower(handle)=lower(?) AND id<>?", (p, h, aid)):
            raise HTTPException(409, f"{h} is already added on {acc.PLATFORMS[p]}.")
        if "platform" in vals and vals["platform"] != cur["platform"] and db.q1(
                "SELECT id FROM assignments WHERE account_id=?", (aid,)):
            raise HTTPException(409, "This account already has clips — remove them before changing its platform.")
    db.update("accounts", aid, **vals)
    return acc.account_out(db.get("accounts", aid))


@router.delete("/api/accounts/{aid}")
def api_delete_account(aid: int):
    """Accounts with history are archived (stats are kept); empty ones are deleted."""
    if db.q1("SELECT id FROM assignments WHERE account_id=? AND status='posted'", (aid,)):
        db.update("accounts", aid, archived=1)
        return {"ok": True, "archived": True}
    db.ex("DELETE FROM assignments WHERE account_id=?", (aid,))
    db.ex("DELETE FROM accounts WHERE id=?", (aid,))
    return {"ok": True, "archived": False}


# ---------------------------------------------------------------- board + assignments
@router.get("/api/board")
def api_board(pool: str = "approved", streamer_id: int | None = None):
    from .pipeline import public_clip
    where = ["c.status <> 'rejected'"]
    args: list = []
    if pool == "approved":
        where.append("c.status IN ('approved','posted')")
    if streamer_id:
        where.append("c.streamer_id=?"); args.append(streamer_id)
    clips = db.q(f"SELECT c.* FROM clips c WHERE {' AND '.join(where)} ORDER BY c.id DESC LIMIT 300", args)
    taken: dict[int, list[str]] = {}
    for r in db.q("SELECT a.clip_id, ac.platform FROM assignments a JOIN accounts ac ON ac.id=a.account_id"):
        taken.setdefault(r["clip_id"], []).append(r["platform"])
    names = {s["id"]: s["name"] for s in db.q("SELECT id, name FROM streamers")}
    pool_out = []
    for c in clips:
        pc = public_clip(c)
        pool_out.append({"id": c["id"], "title": c["title"], "length": pc["length"], "thumb_url": pc["thumb_url"],
                         "streamer": names.get(c["streamer_id"]), "status": c["status"],
                         "render_state": c["render_state"], "platforms": taken.get(c["id"], []),
                         "ready": acc.checklist_complete(c)})
    return {"accounts": acc.list_accounts(), "pool": pool_out, "assignments": acc.list_assignments()}


@router.get("/api/assignments")
def api_assignments(platform: str | None = None, account_id: int | None = None, streamer_id: int | None = None,
                    status: str | None = None):
    return {"assignments": acc.list_assignments(platform=platform or None, account_id=account_id,
                                                streamer_id=streamer_id, status=status or None)}


@router.post("/api/assignments")
async def api_assign(request: Request):
    data = await _json(request)
    try:
        a, warns = _rule(acc.assign, int(data.get("clip_id")), int(data.get("account_id")))
    except (TypeError, ValueError) as e:
        raise HTTPException(400, "clip_id and account_id are required") from e
    return {"assignment": a, "warnings": warns}


@router.delete("/api/assignments/{aid}")
def api_unassign(aid: int):
    acc.unassign(aid)
    return {"ok": True}


@router.post("/api/assignments/{aid}/status")
async def api_move(aid: int, request: Request):
    data = await _json(request)
    a, warns = _rule(acc.move, aid, str(data.get("status", "")), scheduled_at=data.get("scheduled_at"),
                     post_url=data.get("post_url"))
    return {"assignment": a, "warnings": warns}


@router.post("/api/assignments/{aid}/stats")
async def api_stats(aid: int, request: Request):
    data = await _json(request)
    return _rule(acc.log_stats, aid, views=data.get("views"), earnings=data.get("earnings"))


@router.get("/api/clips/{cid}/checklist")
def api_checklist(cid: int):
    c = db.get("clips", cid)
    if not c:
        raise HTTPException(404, "No such clip")
    return {"checklist": acc.checklist(c), "hints": acc.checklist_hints(c), "labels": acc.CHECKLIST}


@router.put("/api/clips/{cid}/checklist")
async def api_set_checklist(cid: int, request: Request):
    data = await _json(request)
    cur = _rule(acc.set_checklist, cid, data)
    c = db.get("clips", cid)
    return {"checklist": cur, "hints": acc.checklist_hints(c), "labels": acc.CHECKLIST}
