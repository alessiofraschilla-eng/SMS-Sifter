"""SQLite lead book: every inbound text, its grade, and one ranked row per phone."""
from __future__ import annotations

import sqlite3
from pathlib import Path

from .gv_ingest import InboundText
from .grader import Grade

SCHEMA = """
CREATE TABLE IF NOT EXISTS messages (
    message_id  TEXT PRIMARY KEY,
    phone       TEXT NOT NULL,
    body        TEXT NOT NULL,
    received_at TEXT NOT NULL,
    score       INTEGER NOT NULL,
    tier        TEXT NOT NULL,
    reasons     TEXT NOT NULL,
    grader      TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS messages_phone ON messages(phone, received_at);
"""

# One row per lead: the latest reply decides the grade, and an opt-out anywhere is sticky.
LEADS_SQL = """
WITH latest AS (
    SELECT m.*, ROW_NUMBER() OVER (PARTITION BY phone ORDER BY received_at DESC) AS rn
    FROM messages m
)
SELECT l.phone,
       CASE WHEN EXISTS (SELECT 1 FROM messages d WHERE d.phone = l.phone AND d.tier = 'DNC')
            THEN 'DNC' ELSE l.tier END AS tier,
       CASE WHEN EXISTS (SELECT 1 FROM messages d WHERE d.phone = l.phone AND d.tier = 'DNC')
            THEN 0 ELSE l.score END AS score,
       l.body AS last_reply, l.reasons, l.received_at AS last_reply_at,
       (SELECT COUNT(*) FROM messages c WHERE c.phone = l.phone) AS replies
FROM latest l WHERE l.rn = 1
ORDER BY CASE tier WHEN 'DNC' THEN 1 ELSE 0 END, score DESC, last_reply_at DESC
"""


class LeadStore:
    def __init__(self, path: str | Path = "leads.db"):
        self.db = sqlite3.connect(str(path))
        self.db.row_factory = sqlite3.Row
        self.db.executescript(SCHEMA)

    def seen(self, message_id: str) -> bool:
        return self.db.execute("SELECT 1 FROM messages WHERE message_id = ?", (message_id,)).fetchone() is not None

    def history(self, phone: str) -> list[str]:
        rows = self.db.execute("SELECT body FROM messages WHERE phone = ? ORDER BY received_at", (phone,))
        return [r["body"] for r in rows]

    def add(self, text: InboundText, grade: Grade) -> None:
        self.db.execute(
            "INSERT OR IGNORE INTO messages VALUES (?,?,?,?,?,?,?,?)",
            (text.message_id, text.phone, text.body, text.received_at.isoformat(),
             grade.score, grade.tier, "; ".join(grade.reasons), grade.grader),
        )
        self.db.commit()

    def ranked_leads(self) -> list[dict]:
        return [dict(r) for r in self.db.execute(LEADS_SQL)]
