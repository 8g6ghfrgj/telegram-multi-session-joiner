# bot/db.py
import os
import sqlite3
from contextlib import contextmanager
from typing import Optional, List, Tuple, Dict, Any

from bot.config import DB_PATH, RESERVE_LINKS

os.makedirs(os.path.dirname(DB_PATH), exist_ok=True)


@contextmanager
def get_conn():
    conn = sqlite3.connect(DB_PATH, timeout=30)
    conn.execute("PRAGMA journal_mode=WAL;")
    conn.execute("PRAGMA synchronous=NORMAL;")
    conn.row_factory = sqlite3.Row
    try:
        yield conn
    finally:
        conn.close()


# ---------------- internal helpers ----------------
def _column_exists(conn: sqlite3.Connection, table: str, col: str) -> bool:
    cur = conn.execute(f"PRAGMA table_info({table})")
    for r in cur.fetchall():
        if r["name"] == col:
            return True
    return False


def _ensure_schema_migrations(conn: sqlite3.Connection) -> None:
    """
    Apply schema migrations safely for existing DB.
    Adds columns to links table:
    - status
    - dead_reason
    - last_checked_at
    """
    if not _column_exists(conn, "links", "status"):
        conn.execute("ALTER TABLE links ADD COLUMN status TEXT DEFAULT 'active';")

    if not _column_exists(conn, "links", "dead_reason"):
        conn.execute("ALTER TABLE links ADD COLUMN dead_reason TEXT;")

    if not _column_exists(conn, "links", "last_checked_at"):
        conn.execute("ALTER TABLE links ADD COLUMN last_checked_at TIMESTAMP;")


# ---------------- init ----------------
def init_db():
    with get_conn() as conn:
        cur = conn.cursor()

        cur.execute("""
        CREATE TABLE IF NOT EXISTS sessions (
          id INTEGER PRIMARY KEY AUTOINCREMENT,
          session_string TEXT UNIQUE NOT NULL,
          phone TEXT,
          created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
          status TEXT DEFAULT 'active'
        );
        """)

        cur.execute("""
        CREATE TABLE IF NOT EXISTS links (
          id INTEGER PRIMARY KEY AUTOINCREMENT,
          link TEXT UNIQUE NOT NULL,
          source_channel TEXT,
          created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        );
        """)

        cur.execute("""
        CREATE TABLE IF NOT EXISTS assignments (
          link_id INTEGER UNIQUE NOT NULL,
          session_id INTEGER NOT NULL,
          assigned_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
          join_status TEXT DEFAULT 'pending',
          join_attempts INTEGER DEFAULT 0,
          last_error TEXT,
          joined_at TIMESTAMP,
          PRIMARY KEY(link_id),
          FOREIGN KEY(link_id) REFERENCES links(id),
          FOREIGN KEY(session_id) REFERENCES sessions(id)
        );
        """)

        cur.execute("""
        CREATE TABLE IF NOT EXISTS join_log (
          id INTEGER PRIMARY KEY AUTOINCREMENT,
          session_id INTEGER,
          link TEXT,
          status TEXT,
          error_message TEXT,
          created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        );
        """)

        # Upgrade existing DB schema
        _ensure_schema_migrations(conn)

        conn.commit()


# ---------------- sessions ----------------
def add_session(session_string: str, phone: str = "") -> bool:
    with get_conn() as conn:
        try:
            conn.execute(
                "INSERT INTO sessions(session_string, phone) VALUES(?,?)",
                (session_string.strip(), phone.strip()),
            )
            conn.commit()
            return True
        except sqlite3.IntegrityError:
            return False


def list_sessions():
    with get_conn() as conn:
        cur = conn.cursor()
        cur.execute("""
            SELECT id, session_string, phone, created_at
            FROM sessions
            WHERE status='active'
            ORDER BY id ASC
        """)
        return [tuple(r) for r in cur.fetchall()]


def soft_delete_session(session_id: int) -> None:
    """
    Soft delete session to avoid losing assigned links permanently.

    Also requeues pending links:
    - delete assignments where join_status='pending'
    so those links become unassigned again.
    """
    with get_conn() as conn:
        conn.execute("UPDATE sessions SET status='deleted' WHERE id=?", (session_id,))

        conn.execute("""
            DELETE FROM assignments
            WHERE session_id=?
              AND join_status='pending'
        """, (session_id,))

        conn.commit()


def delete_session(session_id: int) -> None:
    """
    Backward compatible: delete_session now means SOFT delete.
    """
    soft_delete_session(session_id)


def get_session_by_id(session_id: int):
    with get_conn() as conn:
        cur = conn.cursor()
        cur.execute("""
            SELECT id, session_string, phone, created_at
            FROM sessions
            WHERE id=?
        """, (session_id,))
        row = cur.fetchone()
        return tuple(row) if row else None


# ---------------- links ----------------
def add_links(links: List[str], source_channel: str) -> int:
    """
    Insert links as active by default.
    Dead links are NOT reactivated.
    """
    added = 0
    with get_conn() as conn:
        cur = conn.cursor()
        for link in links:
            link = (link or "").strip()
            if not link:
                continue

            cur.execute(
                "INSERT OR IGNORE INTO links(link, source_channel, status) VALUES(?,?, 'active')",
                (link, source_channel),
            )
            if cur.rowcount > 0:
                added += 1

        conn.commit()
    return added


def mark_link_dead(link_id: int, reason: str = "") -> None:
    with get_conn() as conn:
        conn.execute("""
            UPDATE links
            SET status='dead',
                dead_reason=?,
                last_checked_at=CURRENT_TIMESTAMP
            WHERE id=?
        """, ((reason or "")[:1000], link_id))
        conn.commit()


def count_links_total() -> int:
    with get_conn() as conn:
        return conn.execute("SELECT COUNT(*) FROM links").fetchone()[0]


def count_dead_links() -> int:
    with get_conn() as conn:
        return conn.execute("SELECT COUNT(*) FROM links WHERE status='dead'").fetchone()[0]


def count_links_unassigned_active() -> int:
    """
    Active links that are NOT assigned to any session.
    (Reserve pool base.)
    """
    with get_conn() as conn:
        return conn.execute("""
            SELECT COUNT(*)
            FROM links l
            LEFT JOIN assignments a ON a.link_id = l.id
            WHERE a.link_id IS NULL
              AND (l.status IS NULL OR l.status='active')
        """).fetchone()[0]


def count_links_unassigned_any() -> int:
    """
    Counts ALL unassigned links including dead (informational).
    """
    with get_conn() as conn:
        return conn.execute("""
            SELECT COUNT(*)
            FROM links l
            LEFT JOIN assignments a ON a.link_id = l.id
            WHERE a.link_id IS NULL
        """).fetchone()[0]


def pop_reserve_link() -> Optional[Tuple[int, str]]:
    """
    Get ONE active unassigned link from reserve pool.
    """
    with get_conn() as conn:
        row = conn.execute("""
            SELECT l.id, l.link
            FROM links l
            LEFT JOIN assignments a ON a.link_id = l.id
            WHERE a.link_id IS NULL
              AND (l.status IS NULL OR l.status='active')
            ORDER BY l.id ASC
            LIMIT 1
        """).fetchone()

        if not row:
            return None
        return (row["id"], row["link"])


# ---------------- assignments ----------------
def assign_unassigned_links(session_id: int, limit: int) -> int:
    """
    Assign up to `limit` unassigned ACTIVE links to a session.
    """
    with get_conn() as conn:
        cur = conn.cursor()
        cur.execute("""
            SELECT l.id
            FROM links l
            LEFT JOIN assignments a ON a.link_id = l.id
            WHERE a.link_id IS NULL
              AND (l.status IS NULL OR l.status='active')
            ORDER BY l.id ASC
            LIMIT ?
        """, (limit,))
        rows = cur.fetchall()

        if not rows:
            return 0

        assigned = 0
        for r in rows:
            link_id = r["id"]
            cur.execute("""
                INSERT OR IGNORE INTO assignments(link_id, session_id)
                VALUES(?,?)
            """, (link_id, session_id))
            if cur.rowcount > 0:
                assigned += 1

        conn.commit()
        return assigned


def get_pending_links_for_session(session_id: int, limit: int = 1000):
    """
    Return active links where assignment status is pending.
    """
    with get_conn() as conn:
        cur = conn.cursor()
        cur.execute("""
            SELECT l.id, l.link
            FROM links l
            JOIN assignments a ON a.link_id = l.id
            WHERE a.session_id = ?
              AND a.join_status = 'pending'
              AND (l.status IS NULL OR l.status='active')
            ORDER BY l.id ASC
            LIMIT ?
        """, (session_id, limit))
        return [(r["id"], r["link"]) for r in cur.fetchall()]


def mark_join_success(session_id: int, link_id: int):
    with get_conn() as conn:
        conn.execute("""
            UPDATE assignments
            SET join_status='success',
                joined_at=CURRENT_TIMESTAMP
            WHERE session_id=? AND link_id=?
        """, (session_id, link_id))
        conn.commit()


def mark_join_failed(session_id: int, link_id: int, error: str):
    with get_conn() as conn:
        conn.execute("""
            UPDATE assignments
            SET join_status='failed',
                join_attempts=join_attempts+1,
                last_error=?
            WHERE session_id=? AND link_id=?
        """, ((error or "")[:1000], session_id, link_id))
        conn.commit()


def mark_join_requested(session_id: int, link_id: int, note: str = ""):
    """
    Join Request sent; waiting for admin approval.
    """
    with get_conn() as conn:
        conn.execute("""
            UPDATE assignments
            SET join_status='requested',
                join_attempts=join_attempts+1,
                last_error=?
            WHERE session_id=? AND link_id=?
        """, ((note or "")[:1000], session_id, link_id))
        conn.commit()


def bump_attempt(session_id: int, link_id: int, error: str = ""):
    """
    FloodWait handling: increase attempt count without changing join_status.
    """
    with get_conn() as conn:
        conn.execute("""
            UPDATE assignments
            SET join_attempts=join_attempts+1,
                last_error=?
            WHERE session_id=? AND link_id=?
        """, ((error or "")[:1000], session_id, link_id))
        conn.commit()


def log_join(session_id: int, link: str, status: str, error_message: str = ""):
    with get_conn() as conn:
        conn.execute("""
            INSERT INTO join_log(session_id, link, status, error_message)
            VALUES(?,?,?,?)
        """, (session_id, link, status, (error_message or "")[:1000]))
        conn.commit()


def replace_dead_assignment(
    session_id: int,
    dead_link_id: int,
    dead_reason: str = ""
) -> Optional[Tuple[int, str]]:
    """
    Replace dead link assigned to a session:
    1) mark link dead
    2) delete its assignment
    3) pull new link from reserve (active unassigned)
    4) assign it to same session

    Returns (new_link_id, new_link) or None if reserve empty.
    """
    with get_conn() as conn:
        cur = conn.cursor()

        # 1) mark dead
        cur.execute("""
            UPDATE links
            SET status='dead',
                dead_reason=?,
                last_checked_at=CURRENT_TIMESTAMP
            WHERE id=?
        """, ((dead_reason or "")[:1000], dead_link_id))

        # 2) remove assignment
        cur.execute("""
            DELETE FROM assignments
            WHERE session_id=? AND link_id=?
        """, (session_id, dead_link_id))

        # 3) pick reserve link
        row = cur.execute("""
            SELECT l.id, l.link
            FROM links l
            LEFT JOIN assignments a ON a.link_id = l.id
            WHERE a.link_id IS NULL
              AND (l.status IS NULL OR l.status='active')
            ORDER BY l.id ASC
            LIMIT 1
        """).fetchone()

        if not row:
            conn.commit()
            return None

        new_link_id = row["id"]
        new_link = row["link"]

        # 4) assign
        cur.execute("""
            INSERT OR IGNORE INTO assignments(link_id, session_id)
            VALUES(?,?)
        """, (new_link_id, session_id))

        conn.commit()
        return (new_link_id, new_link)


# ---------------- export functions ----------------
def get_links_for_session_export(session_id: int, limit: int = 1000) -> List[str]:
    """
    Export up to 1000 ACTIVE links assigned to a session.
    (pending/requested/success/failed all included, because the user asked for the session list itself)
    """
    with get_conn() as conn:
        rows = conn.execute("""
            SELECT l.link
            FROM links l
            JOIN assignments a ON a.link_id = l.id
            WHERE a.session_id = ?
              AND (l.status IS NULL OR l.status='active')
            ORDER BY l.id ASC
            LIMIT ?
        """, (session_id, limit)).fetchall()

        return [r["link"] for r in rows]


def get_reserve_links_export(limit: int = 500) -> List[str]:
    """
    Export reserve links:
    - ACTIVE
    - unassigned
    """
    with get_conn() as conn:
        rows = conn.execute("""
            SELECT l.link
            FROM links l
            LEFT JOIN assignments a ON a.link_id = l.id
            WHERE a.link_id IS NULL
              AND (l.status IS NULL OR l.status='active')
            ORDER BY l.id ASC
            LIMIT ?
        """, (limit,)).fetchall()

        return [r["link"] for r in rows]


# ---------------- stats ----------------
def get_stats() -> Dict[str, Any]:
    with get_conn() as conn:
        cur = conn.cursor()

        sessions = cur.execute("""
            SELECT COUNT(*)
            FROM sessions
            WHERE status='active'
        """).fetchone()[0]

        total_links = cur.execute("SELECT COUNT(*) FROM links").fetchone()[0]
        dead_links = cur.execute("SELECT COUNT(*) FROM links WHERE status='dead'").fetchone()[0]

        reserve_links = cur.execute("""
            SELECT COUNT(*)
            FROM links l
            LEFT JOIN assignments a ON a.link_id = l.id
            WHERE a.link_id IS NULL
              AND (l.status IS NULL OR l.status='active')
        """).fetchone()[0]

        unassigned_any = cur.execute("""
            SELECT COUNT(*)
            FROM links l
            LEFT JOIN assignments a ON a.link_id = l.id
            WHERE a.link_id IS NULL
        """).fetchone()[0]

        assigned_total = cur.execute("""
            SELECT COUNT(*)
            FROM assignments a
            JOIN sessions s ON s.id = a.session_id
            WHERE s.status='active'
        """).fetchone()[0]

        pending = cur.execute("SELECT COUNT(*) FROM assignments WHERE join_status='pending'").fetchone()[0]
        requested = cur.execute("SELECT COUNT(*) FROM assignments WHERE join_status='requested'").fetchone()[0]
        success = cur.execute("SELECT COUNT(*) FROM assignments WHERE join_status='success'").fetchone()[0]
        failed = cur.execute("SELECT COUNT(*) FROM assignments WHERE join_status='failed'").fetchone()[0]

        per_session_rows = cur.execute("""
            SELECT
                s.id AS session_id,
                SUM(CASE WHEN a.join_status='pending' THEN 1 ELSE 0 END) AS pending,
                SUM(CASE WHEN a.join_status='requested' THEN 1 ELSE 0 END) AS requested,
                SUM(CASE WHEN a.join_status='success' THEN 1 ELSE 0 END) AS success,
                SUM(CASE WHEN a.join_status='failed' THEN 1 ELSE 0 END) AS failed
            FROM sessions s
            LEFT JOIN assignments a ON a.session_id = s.id
            WHERE s.status='active'
            GROUP BY s.id
            ORDER BY s.id ASC
        """).fetchall()

        per_session = []
        for r in per_session_rows:
            per_session.append({
                "session_id": int(r["session_id"]),
                "pending": int(r["pending"] or 0),
                "requested": int(r["requested"] or 0),
                "success": int(r["success"] or 0),
                "failed": int(r["failed"] or 0),
            })

        return {
            "sessions": sessions,

            "total_links": total_links,
            "dead_links": dead_links,

            "reserve_links": reserve_links,
            "reserve_target": RESERVE_LINKS,

            "assigned": assigned_total,
            "unassigned": unassigned_any,

            "pending": pending,
            "requested": requested,
            "success": success,
            "failed": failed,

            "per_session": per_session,
        }
