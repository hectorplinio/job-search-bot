"""The classified-email history, in SQLite. Same file as the offers and the
oposiciones (one `.db_path`), its own table: see persistence_public.py for
why these do not share one.

This table holds real email content (sender, subject, body) - that is why
`data/` is entirely gitignored, not just the database filename.
"""

from __future__ import annotations

import json
import logging
import sqlite3
from datetime import UTC, datetime
from pathlib import Path

from ..domain.reply_models import ClassifiedReply, EmailReply, ReplyCategory

logger = logging.getLogger(__name__)

SCHEMA = """
CREATE TABLE IF NOT EXISTS email_replies (
    message_id       TEXT PRIMARY KEY,
    thread_id        TEXT NOT NULL,
    sender           TEXT NOT NULL,
    subject          TEXT NOT NULL,
    snippet          TEXT NOT NULL,
    body             TEXT NOT NULL,
    received_at      TEXT NOT NULL,
    category         TEXT NOT NULL,
    matched_keywords TEXT NOT NULL DEFAULT '[]',
    company_guess    TEXT NOT NULL DEFAULT '',
    notified         INTEGER NOT NULL DEFAULT 0,
    first_seen       TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_email_replies_notified ON email_replies(notified, received_at DESC);
"""


def _now() -> str:
    return datetime.now(UTC).isoformat(timespec="seconds")


class SqliteReplyRepository:
    """ports.ReplyRepository implemented on a SQLite file."""

    def __init__(self, db_path: str | Path) -> None:
        self.db_path = Path(db_path)
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self._connection = sqlite3.connect(self.db_path)
        self._connection.row_factory = sqlite3.Row
        self._connection.executescript(SCHEMA)
        self._connection.commit()

    def close(self) -> None:
        self._connection.close()

    def __enter__(self) -> SqliteReplyRepository:
        return self

    def __exit__(self, *_exc_info: object) -> None:
        self.close()

    def is_known(self, message_id: str) -> bool:
        row = self._connection.execute(
            "SELECT 1 FROM email_replies WHERE message_id = ? LIMIT 1", (message_id,)
        ).fetchone()
        return row is not None

    def remember(self, classified: ClassifiedReply, *, notified: bool) -> None:
        reply = classified.reply
        self._connection.execute(
            """
            INSERT INTO email_replies (
                message_id, thread_id, sender, subject, snippet, body,
                received_at, category, matched_keywords, company_guess,
                notified, first_seen
            ) VALUES (?,?,?,?,?,?,?,?,?,?,?,?)
            ON CONFLICT(message_id) DO NOTHING
            """,
            (
                reply.message_id,
                reply.thread_id,
                reply.sender,
                reply.subject,
                reply.snippet,
                reply.body,
                reply.received_at.isoformat(),
                classified.category.value,
                json.dumps(list(classified.matched_keywords), ensure_ascii=False),
                classified.company_guess,
                int(notified),
                _now(),
            ),
        )
        self._connection.commit()

    def mark_notified(self, message_id: str) -> None:
        self._connection.execute(
            "UPDATE email_replies SET notified = 1 WHERE message_id = ?", (message_id,)
        )
        self._connection.commit()

    def pending(self, limit: int = 50) -> list[ClassifiedReply]:
        """Not yet notified, and worth a notification at all - noise and
        auto-confirmations are stored for the record but never alerted."""
        rows = self._connection.execute(
            """
            SELECT * FROM email_replies
            WHERE notified = 0 AND category NOT IN (?, ?)
            ORDER BY received_at DESC
            LIMIT ?
            """,
            (ReplyCategory.NOISE.value, ReplyCategory.AUTO_CONFIRMATION.value, limit),
        ).fetchall()
        return [self._to_classified(row) for row in rows]

    def all(self) -> list[ClassifiedReply]:
        rows = self._connection.execute(
            "SELECT * FROM email_replies ORDER BY received_at ASC"
        ).fetchall()
        return [self._to_classified(row) for row in rows]

    @staticmethod
    def _to_classified(row: sqlite3.Row) -> ClassifiedReply:
        reply = EmailReply(
            message_id=row["message_id"],
            thread_id=row["thread_id"],
            sender=row["sender"],
            subject=row["subject"],
            snippet=row["snippet"],
            body=row["body"],
            received_at=datetime.fromisoformat(row["received_at"]),
        )
        return ClassifiedReply(
            reply=reply,
            category=ReplyCategory(row["category"]),
            matched_keywords=tuple(json.loads(row["matched_keywords"])),
            company_guess=row["company_guess"],
        )
