"""SQLite storage (plain sqlite3, safe to use from worker threads)."""
from __future__ import annotations

import json
import os
import sqlite3
import threading
import time
from pathlib import Path
from typing import Any

_lock = threading.RLock()
_conn: sqlite3.Connection | None = None
_home: Path | None = None


def home() -> Path:
    """App data folder (database, tokens, default media storage)."""
    global _home
    if _home is None:
        env = os.environ.get("CLIPSTUDIO_HOME")
        _home = Path(env) if env else Path.home() / "ClipStudio"
        _home.mkdir(parents=True, exist_ok=True)
    return _home


def set_home(path: Path) -> None:
    """Used by tests: point the app at a scratch folder."""
    global _home, _conn
    with _lock:
        if _conn is not None:
            _conn.close()
            _conn = None
        _home = Path(path)
        _home.mkdir(parents=True, exist_ok=True)


SCHEMA = """
CREATE TABLE IF NOT EXISTS settings (key TEXT PRIMARY KEY, value TEXT);
CREATE TABLE IF NOT EXISTS streamers (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  name TEXT NOT NULL,
  layout TEXT DEFAULT 'split',
  facecam TEXT,                -- JSON {x,y,w,h} fractions of the source frame
  hype_words TEXT DEFAULT '',  -- one phrase per line
  default_tags TEXT DEFAULT '',
  channels TEXT DEFAULT ''     -- channel links, one per line (auto-match jobs)
);
CREATE TABLE IF NOT EXISTS campaigns (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  name TEXT NOT NULL,
  payout_notes TEXT DEFAULT '',
  platforms TEXT DEFAULT '["youtube","tiktok","instagram","x"]',
  min_len REAL DEFAULT 0,
  max_len REAL DEFAULT 0,
  disclosure TEXT DEFAULT '',
  disclosure_seconds REAL DEFAULT 3,
  hashtags TEXT DEFAULT '',
  required_source TEXT DEFAULT '',
  submit_window_min INTEGER DEFAULT 30,
  submit_url TEXT DEFAULT ''
);
CREATE TABLE IF NOT EXISTS jobs (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  url TEXT NOT NULL,
  platform TEXT,
  is_live INTEGER DEFAULT 0,
  title TEXT DEFAULT '',
  channel TEXT DEFAULT '',
  duration REAL,
  streamer_id INTEGER,
  campaign_id INTEGER,
  options TEXT DEFAULT '{}',
  status TEXT DEFAULT 'queued',
  stage TEXT DEFAULT 'queued',
  progress REAL DEFAULT 0,
  error TEXT,
  ai_input_tokens INTEGER DEFAULT 0,
  ai_output_tokens INTEGER DEFAULT 0,
  ai_cost REAL DEFAULT 0,
  created REAL,
  started REAL,
  finished REAL
);
CREATE TABLE IF NOT EXISTS clips (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  job_id INTEGER,
  streamer_id INTEGER,
  campaign_id INTEGER,
  start REAL, "end" REAL, peak REAL,
  score REAL, ai_score REAL,
  reason TEXT DEFAULT '',
  title TEXT DEFAULT '',
  hook TEXT DEFAULT '',
  description TEXT DEFAULT '',
  status TEXT DEFAULT 'pending',     -- pending/approved/rejected/posted
  render_state TEXT DEFAULT 'queued', -- queued/rendering/ready/error
  render_error TEXT,
  layout TEXT,
  src_path TEXT, src_offset REAL DEFAULT 0, src_end REAL,
  video_path TEXT, thumb_path TEXT, gif_path TEXT,
  disclosure_burned INTEGER DEFAULT 0,
  youtube_id TEXT, publish_at TEXT, yt_state TEXT, yt_error TEXT, yt_retry_after REAL,
  posted_url TEXT, posted_at REAL, submitted INTEGER DEFAULT 0,
  signals TEXT DEFAULT '{}',
  source_url TEXT, source_extra TEXT DEFAULT '{}',
  created REAL
);
CREATE TABLE IF NOT EXISTS posts (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  clip_id INTEGER, platform TEXT, url TEXT,
  posted_at REAL, submitted INTEGER DEFAULT 0, submitted_at REAL
);
CREATE INDEX IF NOT EXISTS clips_job ON clips(job_id);
CREATE INDEX IF NOT EXISTS clips_status ON clips(status);
"""


def conn() -> sqlite3.Connection:
    global _conn
    with _lock:
        if _conn is None:
            _conn = sqlite3.connect(str(home() / "clipstudio.db"), check_same_thread=False,
                                    isolation_level=None, timeout=30)
            _conn.row_factory = sqlite3.Row
            _conn.execute("PRAGMA journal_mode=WAL")
            _conn.executescript(SCHEMA)
            _migrate(_conn)
            _seed(_conn)
        return _conn


MIGRATIONS = [  # (table, column, type) added after the first release
    ("clips", "source_url", "TEXT"), ("clips", "source_extra", "TEXT DEFAULT '{}'"),
]


def _migrate(c: sqlite3.Connection) -> None:
    for table, col, typ in MIGRATIONS:
        cols = {r[1] for r in c.execute(f"PRAGMA table_info({table})")}
        if col not in cols:
            c.execute(f'ALTER TABLE {table} ADD COLUMN "{col}" {typ}')


def _seed(c: sqlite3.Connection) -> None:
    if c.execute("SELECT COUNT(*) FROM streamers").fetchone()[0] == 0:
        for name in ("Lacy", "Marlon"):
            c.execute("INSERT INTO streamers(name, layout, hype_words) VALUES (?,?,?)",
                      (name, "split", ""))


def q(sql: str, args: tuple | list = ()) -> list[dict]:
    with _lock:
        return [dict(r) for r in conn().execute(sql, args).fetchall()]


def q1(sql: str, args: tuple | list = ()) -> dict | None:
    rows = q(sql, args)
    return rows[0] if rows else None


def ex(sql: str, args: tuple | list = ()) -> int:
    with _lock:
        cur = conn().execute(sql, args)
        return cur.lastrowid


def insert(table: str, **vals: Any) -> int:
    cols = ",".join(f'"{k}"' for k in vals)
    marks = ",".join("?" for _ in vals)
    return ex(f"INSERT INTO {table} ({cols}) VALUES ({marks})", list(vals.values()))


def update(table: str, row_id: int, **vals: Any) -> None:
    if not vals:
        return
    sets = ",".join(f'"{k}"=?' for k in vals)
    ex(f"UPDATE {table} SET {sets} WHERE id=?", [*vals.values(), row_id])


def get(table: str, row_id: int) -> dict | None:
    return q1(f"SELECT * FROM {table} WHERE id=?", (row_id,))


# ---------------------------------------------------------------- settings
DEFAULTS: dict[str, Any] = {
    "clip_count": 8,
    "min_len": 20,
    "max_len": 60,
    "default_layout": "split",
    "w_chat": 1.0,
    "w_audio": 1.0,
    "w_transcript": 0.8,
    "w_clips": 1.5,
    "hype_tokens": "LUL, KEKW, OMEGALUL, LMAO, 💀, 😂, W, L, ???, !!!, no way, clip it, clip that, bro, nah",
    "whisper_model": "small.en",
    "whisper_device": "auto",
    "transcribe_mode": "smart",       # smart = only around candidates on long videos; full = everything
    "ai_enabled": False,
    "anthropic_api_key": "",
    "ai_model": "claude-sonnet-5-5",
    "ai_min_score": 6,
    "caption_font": "Arial",
    "caption_size": 84,
    "caption_color": "#FFFFFF",
    "caption_highlight": "#FFE600",
    "caption_words": 3,
    "yt_slots": "11:00, 15:00, 19:00, 22:00",
    "timezone": "America/New_York",
    "discord_webhook": "",
    "storage_dir": "",
    "max_disk_gb": 60.0,
    "keep_source": False,
    "max_video_hours": 12.0,
    "live_catchup_hours": 3.0,
    "live_threshold": 2.2,
    "live_tail": 10,
    "live_keep_minutes": 120,
    "max_parallel_jobs": 2,
    "yt_cookies_browser": "",
}

SECRET_KEYS = {"anthropic_api_key"}


def setting(key: str) -> Any:
    row = q1("SELECT value FROM settings WHERE key=?", (key,))
    if row is None:
        return DEFAULTS.get(key)
    try:
        return json.loads(row["value"])
    except (ValueError, TypeError):
        return row["value"]


def all_settings() -> dict[str, Any]:
    out = dict(DEFAULTS)
    for r in q("SELECT key, value FROM settings"):
        try:
            out[r["key"]] = json.loads(r["value"])
        except (ValueError, TypeError):
            out[r["key"]] = r["value"]
    return out


def set_setting(key: str, value: Any) -> None:
    ex("INSERT INTO settings(key,value) VALUES(?,?) ON CONFLICT(key) DO UPDATE SET value=excluded.value",
       (key, json.dumps(value)))


def storage_dir() -> Path:
    s = setting("storage_dir")
    p = Path(s).expanduser() if s else home() / "media"
    p.mkdir(parents=True, exist_ok=True)
    return p


def now() -> float:
    return time.time()
