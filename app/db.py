"""SQLite storage layer. One shared connection guarded by a lock — the app is
single-process and low-concurrency, so this stays simple (no ORM)."""

import json
import logging
import os
import shutil
import sqlite3
import threading
from datetime import datetime, timezone
from pathlib import Path

from . import config

log = logging.getLogger("batterbox.db")

_lock = threading.RLock()
_conn: sqlite3.Connection | None = None

SCHEMA = """
CREATE TABLE IF NOT EXISTS teams (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  name TEXT NOT NULL,
  sort_order INTEGER NOT NULL DEFAULT 0
);
CREATE TABLE IF NOT EXISTS players (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  team_id INTEGER NOT NULL REFERENCES teams(id) ON DELETE CASCADE,
  name TEXT NOT NULL,
  jersey_number INTEGER,
  photo_url TEXT,
  sort_order INTEGER NOT NULL DEFAULT 0,
  absent INTEGER NOT NULL DEFAULT 0
);
CREATE TABLE IF NOT EXISTS clips (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  player_id INTEGER NOT NULL REFERENCES players(id) ON DELETE CASCADE,
  type TEXT NOT NULL CHECK (type IN ('walkup','homerun','walkout')),
  is_active INTEGER NOT NULL DEFAULT 0,
  source TEXT NOT NULL,
  source_url TEXT,
  duration_sec REAL,
  trim_start_sec REAL,
  trim_end_sec REAL,
  fade_in_ms INTEGER NOT NULL DEFAULT 0,
  fade_out_ms INTEGER NOT NULL DEFAULT 0,
  volume_boost_db REAL NOT NULL DEFAULT 0,
  source_file TEXT,
  created_at TEXT
);
CREATE TABLE IF NOT EXISTS hype (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  title TEXT NOT NULL,
  source TEXT,
  source_url TEXT,
  duration_sec REAL,
  trim_start_sec REAL,
  trim_end_sec REAL,
  fade_in_ms INTEGER NOT NULL DEFAULT 0,
  fade_out_ms INTEGER NOT NULL DEFAULT 0,
  volume_boost_db REAL NOT NULL DEFAULT 0,
  source_file TEXT,
  created_at TEXT
);
CREATE TABLE IF NOT EXISTS settings (
  key TEXT PRIMARY KEY,
  value TEXT
);
"""


def get_conn() -> sqlite3.Connection:
    global _conn
    if _conn is None:
        os.makedirs(config.DATA_DIR, exist_ok=True)
        _conn = sqlite3.connect(
            os.path.join(config.DATA_DIR, "batterbox.db"), check_same_thread=False
        )
        _conn.row_factory = sqlite3.Row
        _conn.execute("PRAGMA foreign_keys = ON")
    return _conn


def init_db() -> None:
    with _lock:
        conn = get_conn()
        conn.executescript(SCHEMA)
        _migrate(conn)
        for sub in ("clips", "sources", "photos", "hype"):
            os.makedirs(os.path.join(config.DATA_DIR, sub), exist_ok=True)
        defaults = {
            "default_snippet_length": "30",
            "master_volume": "80",
            "audio_output": config.AUDIO_OUTPUT,
            "mock_gpio": "true" if config.MOCK_GPIO else "false",
            # Wi-Fi hotspot credentials (plain text by design — private-LAN
            # appliance, no auth; admin UI reads the password back aloud)
            "wifi_ssid": "BatterBox",
            "wifi_password": "bigleague1",
            # GPIO pins (not part of the public settings contract)
            "gpio_stop_pin": "17",
            "gpio_volume_up_pin": "27",
            "gpio_volume_down_pin": "22",
            "gpio_next_pin": "23",
        }
        for key, value in defaults.items():
            conn.execute(
                "INSERT OR IGNORE INTO settings (key, value) VALUES (?, ?)", (key, value)
            )
        conn.commit()
        _seed_if_empty(conn)


def _migrate(conn: sqlite3.Connection) -> None:
    """Non-destructive upgrades for DBs created by older versions."""
    cols = [r["name"] for r in conn.execute("PRAGMA table_info(clips)")]
    if "source_file" not in cols:
        conn.execute("ALTER TABLE clips ADD COLUMN source_file TEXT")
        conn.commit()
        log.info("Migrated clips table: added source_file column")
    pcols = [r["name"] for r in conn.execute("PRAGMA table_info(players)")]
    if "absent" not in pcols:
        conn.execute(
            "ALTER TABLE players ADD COLUMN absent INTEGER NOT NULL DEFAULT 0"
        )
        conn.commit()
        log.info("Migrated players table: added absent column")

    # SQLite can't ALTER a CHECK constraint — rebuild clips atomically when the
    # old ('walkup','homerun')-only CHECK is present so 'walkout' is accepted.
    row = conn.execute(
        "SELECT sql FROM sqlite_master WHERE type = 'table' AND name = 'clips'"
    ).fetchone()
    if row and row["sql"] and "walkout" not in row["sql"]:
        conn.execute("BEGIN")
        try:
            conn.execute(
                """
                CREATE TABLE clips_new (
                  id INTEGER PRIMARY KEY AUTOINCREMENT,
                  player_id INTEGER NOT NULL REFERENCES players(id) ON DELETE CASCADE,
                  type TEXT NOT NULL CHECK (type IN ('walkup','homerun','walkout')),
                  is_active INTEGER NOT NULL DEFAULT 0,
                  source TEXT NOT NULL,
                  source_url TEXT,
                  duration_sec REAL,
                  trim_start_sec REAL,
                  trim_end_sec REAL,
                  fade_in_ms INTEGER NOT NULL DEFAULT 0,
                  fade_out_ms INTEGER NOT NULL DEFAULT 0,
                  volume_boost_db REAL NOT NULL DEFAULT 0,
                  source_file TEXT,
                  created_at TEXT
                )
                """
            )
            conn.execute(
                "INSERT INTO clips_new (id, player_id, type, is_active, source,"
                " source_url, duration_sec, trim_start_sec, trim_end_sec,"
                " fade_in_ms, fade_out_ms, volume_boost_db, source_file,"
                " created_at)"
                " SELECT id, player_id, type, is_active, source, source_url,"
                " duration_sec, trim_start_sec, trim_end_sec, fade_in_ms,"
                " fade_out_ms, volume_boost_db, source_file, created_at FROM clips"
            )
            conn.execute("DROP TABLE clips")
            conn.execute("ALTER TABLE clips_new RENAME TO clips")
            conn.commit()
        except Exception:
            conn.rollback()
            raise
        log.info("Migrated clips table: rebuilt with 'walkout' in the type CHECK")

    # Snippet default grew 12s -> 30s; upgrade only untouched defaults.
    cur = conn.execute(
        "UPDATE settings SET value = '30'"
        " WHERE key = 'default_snippet_length' AND value = '12'"
    )
    if cur.rowcount:
        conn.commit()
        log.info("Migrated settings: default_snippet_length 12 -> 30")


def _seed_if_empty(conn: sqlite3.Connection) -> None:
    row = conn.execute("SELECT COUNT(*) AS c FROM teams").fetchone()
    if row["c"] > 0:
        return
    seed_file = Path(__file__).resolve().parent.parent / "seed.json"
    if not seed_file.exists():
        log.warning("seed.json not found at %s; starting with empty DB", seed_file)
        return
    data = json.loads(seed_file.read_text(encoding="utf-8"))
    first_team_id = None
    for t_order, team in enumerate(data.get("teams", [])):
        cur = conn.execute(
            "INSERT INTO teams (name, sort_order) VALUES (?, ?)", (team["name"], t_order)
        )
        team_id = cur.lastrowid
        if first_team_id is None:
            first_team_id = team_id
        for p_order, player in enumerate(team.get("players", [])):
            cur = conn.execute(
                "INSERT INTO players (team_id, name, jersey_number, sort_order)"
                " VALUES (?, ?, ?, ?)",
                (team_id, player["name"], player.get("jersey_number"), p_order),
            )
            player_id = cur.lastrowid
            for clip in player.get("clips", []):
                _seed_clip(conn, seed_file.parent, player_id, clip)
    if first_team_id is not None:
        conn.execute(
            "INSERT OR REPLACE INTO settings (key, value) VALUES ('active_team_id', ?)",
            (str(first_team_id),),
        )
    conn.commit()
    log.info("Seeded database from %s", seed_file)


def _seed_clip(conn: sqlite3.Connection, seed_dir: Path, player_id: int, clip: dict) -> None:
    """Seed one clip row + copy its bundled mp3 (seed/clips/<file>) into
    DATA_DIR/clips/<id>.mp3. Seeded clips have no source_file, so they are not
    re-editable in the trim editor (re-import to re-trim)."""
    src = seed_dir / "seed" / "clips" / clip["file"]
    if not src.exists():
        log.warning("Seed clip file missing: %s — skipping", src)
        return
    cur = conn.execute(
        "INSERT INTO clips (player_id, type, is_active, source, source_url,"
        " duration_sec, trim_start_sec, trim_end_sec, fade_in_ms, fade_out_ms,"
        " volume_boost_db, source_file, created_at)"
        " VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, NULL, ?)",
        (
            player_id,
            clip["type"],
            1 if clip.get("is_active") else 0,
            clip.get("source", "upload"),
            clip.get("source_url"),
            clip["duration_sec"],
            clip["trim_start_sec"],
            clip["trim_end_sec"],
            clip.get("fade_in_ms", 300),
            clip.get("fade_out_ms", 500),
            clip.get("volume_boost_db", 0.0),
            datetime.now(timezone.utc).isoformat(),
        ),
    )
    dst = os.path.join(config.DATA_DIR, "clips", f"{cur.lastrowid}.mp3")
    shutil.copyfile(src, dst)


# ---------------------------------------------------------------- settings


def get_setting(key: str, default: str | None = None) -> str | None:
    with _lock:
        row = get_conn().execute(
            "SELECT value FROM settings WHERE key = ?", (key,)
        ).fetchone()
    return row["value"] if row else default


def set_setting(key: str, value) -> None:
    with _lock:
        conn = get_conn()
        conn.execute(
            "INSERT OR REPLACE INTO settings (key, value) VALUES (?, ?)",
            (key, str(value)),
        )
        conn.commit()


def public_settings() -> dict:
    return {
        "default_snippet_length": int(get_setting("default_snippet_length", "30")),
        "master_volume": int(get_setting("master_volume", "80")),
        "audio_output": get_setting("audio_output", "auto"),
        "mock_gpio": get_setting("mock_gpio", "true") == "true",
    }


def get_active_team_id() -> int | None:
    raw = get_setting("active_team_id")
    return int(raw) if raw else None


def set_active_team_id(team_id: int) -> None:
    set_setting("active_team_id", str(team_id))


# ------------------------------------------------------------------- teams


def _team_to_dict(row: sqlite3.Row) -> dict:
    return {
        "id": row["id"],
        "name": row["name"],
        "sort_order": row["sort_order"],
        "player_count": row["player_count"],
    }


_TEAM_SELECT = (
    "SELECT t.*, (SELECT COUNT(*) FROM players p WHERE p.team_id = t.id)"
    " AS player_count FROM teams t"
)


def list_teams() -> list[dict]:
    with _lock:
        rows = get_conn().execute(_TEAM_SELECT + " ORDER BY t.sort_order, t.id").fetchall()
    return [_team_to_dict(r) for r in rows]


def get_team(team_id: int) -> dict | None:
    with _lock:
        row = get_conn().execute(_TEAM_SELECT + " WHERE t.id = ?", (team_id,)).fetchone()
    return _team_to_dict(row) if row else None


def create_team(name: str) -> dict:
    with _lock:
        conn = get_conn()
        nxt = conn.execute(
            "SELECT COALESCE(MAX(sort_order), -1) + 1 AS n FROM teams"
        ).fetchone()["n"]
        cur = conn.execute("INSERT INTO teams (name, sort_order) VALUES (?, ?)", (name, nxt))
        conn.commit()
    # The only team should always be the active one — otherwise the kiosk
    # renders a grid (frontend falls back to the first team) while next-batter
    # 404s with "no active team".
    if get_active_team_id() is None:
        set_active_team_id(cur.lastrowid)
    return get_team(cur.lastrowid)


def update_team(team_id: int, name: str) -> dict | None:
    with _lock:
        conn = get_conn()
        cur = conn.execute("UPDATE teams SET name = ? WHERE id = ?", (name, team_id))
        conn.commit()
        if cur.rowcount == 0:
            return None
    return get_team(team_id)


def delete_team(team_id: int) -> bool:
    with _lock:
        conn = get_conn()
        clips = conn.execute(
            "SELECT c.id, c.source_file FROM clips c JOIN players p ON c.player_id = p.id"
            " WHERE p.team_id = ?",
            (team_id,),
        ).fetchall()
        photos = [
            r["photo_url"]
            for r in conn.execute(
                "SELECT photo_url FROM players WHERE team_id = ? AND photo_url IS NOT NULL",
                (team_id,),
            )
        ]
        cur = conn.execute("DELETE FROM teams WHERE id = ?", (team_id,))
        if get_active_team_id() == team_id:
            # Hand the active slot to the first remaining team instead of
            # leaving it unset (kiosk would render a fallback team while
            # next-batter fails with "no active team").
            successor = conn.execute(
                "SELECT id FROM teams ORDER BY sort_order, id LIMIT 1"
            ).fetchone()
            if successor:
                conn.execute(
                    "INSERT OR REPLACE INTO settings (key, value) VALUES"
                    " ('active_team_id', ?)",
                    (str(successor["id"]),),
                )
            else:
                conn.execute("DELETE FROM settings WHERE key = 'active_team_id'")
        conn.commit()
    if cur.rowcount:
        _remove_files(
            [c["id"] for c in clips],
            photos,
            [c["source_file"] for c in clips if c["source_file"]],
        )
    return cur.rowcount > 0


def _unlink_quietly(path: str) -> None:
    """Remove a file, tolerating a concurrent delete of the same path.
    exists()-then-remove() is TOCTOU: two deletes of clips that share a
    source file both see it present, and the loser would otherwise raise
    an uncaught FileNotFoundError that 500s an already-successful delete."""
    try:
        os.remove(path)
    except FileNotFoundError:
        pass
    except OSError as e:
        log.warning("could not remove %s: %s", path, e)


def _remove_files(
    clip_ids: list[int],
    photo_urls: list[str],
    source_files: list[str] | None = None,
) -> None:
    for cid in clip_ids:
        _unlink_quietly(os.path.join(config.DATA_DIR, "clips", f"{cid}.mp3"))
    for url in photo_urls:
        _unlink_quietly(os.path.join(config.DATA_DIR, "photos", os.path.basename(url)))
    # Trim sources leak forever otherwise (roster churn grows the volume
    # unbounded). Called AFTER the rows are deleted, so the reference check
    # sees only surviving clips/hype — a source shared with them is kept.
    for name in source_files or []:
        if not name or source_file_referenced(name):
            continue
        _unlink_quietly(os.path.join(config.DATA_DIR, "sources", os.path.basename(name)))


# ----------------------------------------------------------------- players


_PLAYER_SELECT = """
SELECT p.*,
 (SELECT c.id FROM clips c WHERE c.player_id = p.id AND c.type = 'walkup'
   AND c.is_active = 1 LIMIT 1) AS active_walkup_clip_id,
 (SELECT c.id FROM clips c WHERE c.player_id = p.id AND c.type = 'homerun'
   AND c.is_active = 1 LIMIT 1) AS active_homerun_clip_id,
 (SELECT c.id FROM clips c WHERE c.player_id = p.id AND c.type = 'walkout'
   AND c.is_active = 1 LIMIT 1) AS active_walkout_clip_id
FROM players p
"""


def _player_to_dict(row: sqlite3.Row) -> dict:
    return {
        "id": row["id"],
        "team_id": row["team_id"],
        "name": row["name"],
        "jersey_number": row["jersey_number"],
        "photo_url": row["photo_url"],
        "sort_order": row["sort_order"],
        "absent": bool(row["absent"]),
        "active_walkup_clip_id": row["active_walkup_clip_id"],
        "active_homerun_clip_id": row["active_homerun_clip_id"],
        "active_walkout_clip_id": row["active_walkout_clip_id"],
    }


def list_players(team_id: int) -> list[dict]:
    with _lock:
        rows = get_conn().execute(
            _PLAYER_SELECT + " WHERE p.team_id = ? ORDER BY p.sort_order, p.id",
            (team_id,),
        ).fetchall()
    return [_player_to_dict(r) for r in rows]


def get_player(player_id: int) -> dict | None:
    with _lock:
        row = get_conn().execute(
            _PLAYER_SELECT + " WHERE p.id = ?", (player_id,)
        ).fetchone()
    return _player_to_dict(row) if row else None


def create_player(team_id: int, name: str, jersey_number: int | None) -> dict:
    with _lock:
        conn = get_conn()
        nxt = conn.execute(
            "SELECT COALESCE(MAX(sort_order), -1) + 1 AS n FROM players WHERE team_id = ?",
            (team_id,),
        ).fetchone()["n"]
        cur = conn.execute(
            "INSERT INTO players (team_id, name, jersey_number, sort_order)"
            " VALUES (?, ?, ?, ?)",
            (team_id, name, jersey_number, nxt),
        )
        conn.commit()
    return get_player(cur.lastrowid)


def update_player(player_id: int, fields: dict) -> dict | None:
    """Apply a partial update; `fields` may contain 'name', 'jersey_number', 'absent'."""
    allowed = {"name", "jersey_number", "absent"}
    assignments = [(k, v) for k, v in fields.items() if k in allowed]
    with _lock:
        conn = get_conn()
        for key, value in assignments:
            conn.execute(
                f"UPDATE players SET {key} = ? WHERE id = ?", (value, player_id)
            )
        conn.commit()
    return get_player(player_id)


def set_player_photo(player_id: int, photo_url: str) -> None:
    with _lock:
        conn = get_conn()
        conn.execute(
            "UPDATE players SET photo_url = ? WHERE id = ?", (photo_url, player_id)
        )
        conn.commit()


def delete_player(player_id: int) -> bool:
    with _lock:
        conn = get_conn()
        row = conn.execute(
            "SELECT photo_url FROM players WHERE id = ?", (player_id,)
        ).fetchone()
        if row is None:
            return False
        clips = conn.execute(
            "SELECT id, source_file FROM clips WHERE player_id = ?", (player_id,)
        ).fetchall()
        conn.execute("DELETE FROM players WHERE id = ?", (player_id,))
        conn.commit()
    photos = [row["photo_url"]] if row["photo_url"] else []
    _remove_files(
        [c["id"] for c in clips],
        photos,
        [c["source_file"] for c in clips if c["source_file"]],
    )
    return True


def reorder_players(team_id: int, player_ids: list[int]) -> None:
    with _lock:
        conn = get_conn()
        for pos, pid in enumerate(player_ids):
            conn.execute(
                "UPDATE players SET sort_order = ? WHERE id = ? AND team_id = ?",
                (pos, pid, team_id),
            )
        conn.commit()


# ------------------------------------------------------------------- clips


def _clip_to_dict(row: sqlite3.Row) -> dict:
    return {
        "id": row["id"],
        "player_id": row["player_id"],
        "type": row["type"],
        "is_active": bool(row["is_active"]),
        "source": row["source"],
        "source_url": row["source_url"],
        "audio_url": f"/media/clips/{row['id']}.mp3",
        "duration_sec": row["duration_sec"],
        "trim_start_sec": row["trim_start_sec"],
        "trim_end_sec": row["trim_end_sec"],
        "fade_in_ms": row["fade_in_ms"],
        "fade_out_ms": row["fade_out_ms"],
        "volume_boost_db": row["volume_boost_db"],
        "created_at": row["created_at"],
    }


def list_clips(player_id: int) -> list[dict]:
    with _lock:
        rows = get_conn().execute(
            "SELECT * FROM clips WHERE player_id = ? ORDER BY id", (player_id,)
        ).fetchall()
    return [_clip_to_dict(r) for r in rows]


def get_clip(clip_id: int) -> dict | None:
    with _lock:
        row = get_conn().execute("SELECT * FROM clips WHERE id = ?", (clip_id,)).fetchone()
    return _clip_to_dict(row) if row else None


def get_active_clip(player_id: int, clip_type: str) -> dict | None:
    with _lock:
        row = get_conn().execute(
            "SELECT * FROM clips WHERE player_id = ? AND type = ? AND is_active = 1",
            (player_id, clip_type),
        ).fetchone()
    return _clip_to_dict(row) if row else None


def insert_clip(
    player_id: int,
    clip_type: str,
    source: str,
    source_url: str | None,
    duration_sec: float,
    trim_start_sec: float,
    trim_end_sec: float,
    fade_in_ms: int,
    fade_out_ms: int,
    volume_boost_db: float,
    source_file: str | None = None,
) -> int:
    with _lock:
        conn = get_conn()
        # First clip of a player+type becomes active. Decided inside the same
        # lock as the insert so two concurrent first-saves can't both count
        # zero and both insert as active.
        is_active = (
            conn.execute(
                "SELECT COUNT(*) AS c FROM clips WHERE player_id = ? AND type = ?",
                (player_id, clip_type),
            ).fetchone()["c"]
            == 0
        )
        cur = conn.execute(
            "INSERT INTO clips (player_id, type, is_active, source, source_url,"
            " duration_sec, trim_start_sec, trim_end_sec, fade_in_ms, fade_out_ms,"
            " volume_boost_db, source_file, created_at)"
            " VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (
                player_id,
                clip_type,
                1 if is_active else 0,
                source,
                source_url,
                duration_sec,
                trim_start_sec,
                trim_end_sec,
                fade_in_ms,
                fade_out_ms,
                volume_boost_db,
                source_file,
                datetime.now(timezone.utc).isoformat(),
            ),
        )
        conn.commit()
        return cur.lastrowid


def source_file_referenced(basename: str) -> bool:
    """True if any clip or hype row still points at sources/<basename>."""
    with _lock:
        conn = get_conn()
        clip = conn.execute(
            "SELECT 1 FROM clips WHERE source_file = ? LIMIT 1", (basename,)
        ).fetchone()
        if clip:
            return True
        hype = conn.execute(
            "SELECT 1 FROM hype WHERE source_file = ? LIMIT 1", (basename,)
        ).fetchone()
        return hype is not None


def get_clip_source_file(clip_id: int) -> str | None:
    """Internal: relative filename of the clip's full-length source in sources/."""
    with _lock:
        row = get_conn().execute(
            "SELECT source_file FROM clips WHERE id = ?", (clip_id,)
        ).fetchone()
    return row["source_file"] if row else None


def update_clip_trim(
    clip_id: int,
    duration_sec: float,
    trim_start_sec: float,
    trim_end_sec: float,
    fade_in_ms: int,
    fade_out_ms: int,
    volume_boost_db: float,
) -> None:
    with _lock:
        conn = get_conn()
        conn.execute(
            "UPDATE clips SET duration_sec = ?, trim_start_sec = ?, trim_end_sec = ?,"
            " fade_in_ms = ?, fade_out_ms = ?, volume_boost_db = ? WHERE id = ?",
            (
                duration_sec,
                trim_start_sec,
                trim_end_sec,
                fade_in_ms,
                fade_out_ms,
                volume_boost_db,
                clip_id,
            ),
        )
        conn.commit()


def activate_clip(clip_id: int) -> None:
    with _lock:
        conn = get_conn()
        row = conn.execute("SELECT * FROM clips WHERE id = ?", (clip_id,)).fetchone()
        if row is None:
            return
        conn.execute(
            "UPDATE clips SET is_active = 0 WHERE player_id = ? AND type = ?",
            (row["player_id"], row["type"]),
        )
        conn.execute("UPDATE clips SET is_active = 1 WHERE id = ?", (clip_id,))
        conn.commit()


def delete_clip(clip_id: int) -> bool:
    with _lock:
        conn = get_conn()
        row = conn.execute(
            "SELECT source_file FROM clips WHERE id = ?", (clip_id,)
        ).fetchone()
        cur = conn.execute("DELETE FROM clips WHERE id = ?", (clip_id,))
        conn.commit()
    if cur.rowcount:
        _remove_files([clip_id], [], [row["source_file"]] if row else [])
    return cur.rowcount > 0


# -------------------------------------------------------------------- hype


def _hype_to_dict(row: sqlite3.Row) -> dict:
    return {
        "id": row["id"],
        "title": row["title"],
        "source": row["source"],
        "source_url": row["source_url"],
        "audio_url": f"/media/hype/{row['id']}.mp3",
        "duration_sec": row["duration_sec"],
        "trim_start_sec": row["trim_start_sec"],
        "trim_end_sec": row["trim_end_sec"],
        "fade_in_ms": row["fade_in_ms"],
        "fade_out_ms": row["fade_out_ms"],
        "volume_boost_db": row["volume_boost_db"],
        "created_at": row["created_at"],
    }


def list_hype() -> list[dict]:
    with _lock:
        rows = get_conn().execute("SELECT * FROM hype ORDER BY id").fetchall()
    return [_hype_to_dict(r) for r in rows]


def get_hype(hype_id: int) -> dict | None:
    with _lock:
        row = get_conn().execute("SELECT * FROM hype WHERE id = ?", (hype_id,)).fetchone()
    return _hype_to_dict(row) if row else None


def insert_hype(
    title: str,
    source: str,
    source_url: str | None,
    duration_sec: float,
    trim_start_sec: float,
    trim_end_sec: float,
    fade_in_ms: int,
    fade_out_ms: int,
    volume_boost_db: float,
    source_file: str | None = None,
) -> int:
    with _lock:
        conn = get_conn()
        cur = conn.execute(
            "INSERT INTO hype (title, source, source_url, duration_sec,"
            " trim_start_sec, trim_end_sec, fade_in_ms, fade_out_ms,"
            " volume_boost_db, source_file, created_at)"
            " VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (
                title,
                source,
                source_url,
                duration_sec,
                trim_start_sec,
                trim_end_sec,
                fade_in_ms,
                fade_out_ms,
                volume_boost_db,
                source_file,
                datetime.now(timezone.utc).isoformat(),
            ),
        )
        conn.commit()
        return cur.lastrowid


def get_hype_source_file(hype_id: int) -> str | None:
    """Internal: relative filename of the hype clip's full source in sources/."""
    with _lock:
        row = get_conn().execute(
            "SELECT source_file FROM hype WHERE id = ?", (hype_id,)
        ).fetchone()
    return row["source_file"] if row else None


def update_hype_trim(
    hype_id: int,
    duration_sec: float,
    trim_start_sec: float,
    trim_end_sec: float,
    fade_in_ms: int,
    fade_out_ms: int,
    volume_boost_db: float,
) -> None:
    with _lock:
        conn = get_conn()
        conn.execute(
            "UPDATE hype SET duration_sec = ?, trim_start_sec = ?, trim_end_sec = ?,"
            " fade_in_ms = ?, fade_out_ms = ?, volume_boost_db = ? WHERE id = ?",
            (
                duration_sec,
                trim_start_sec,
                trim_end_sec,
                fade_in_ms,
                fade_out_ms,
                volume_boost_db,
                hype_id,
            ),
        )
        conn.commit()


def delete_hype(hype_id: int) -> bool:
    with _lock:
        conn = get_conn()
        row = conn.execute(
            "SELECT source_file FROM hype WHERE id = ?", (hype_id,)
        ).fetchone()
        cur = conn.execute("DELETE FROM hype WHERE id = ?", (hype_id,))
        conn.commit()
    if cur.rowcount:
        _unlink_quietly(os.path.join(config.DATA_DIR, "hype", f"{hype_id}.mp3"))
        _remove_files([], [], [row["source_file"]] if row else [])
    return cur.rowcount > 0
