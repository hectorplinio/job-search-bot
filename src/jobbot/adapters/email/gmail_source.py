"""Gmail, read-only, through the REST API directly (no google-api-python-client:
one more heavy dependency for three endpoints we can call with httpx like
every other source here).

Auth is OAuth2 with a long-lived refresh token generated once by
`scripts/gmail_oauth_setup.py` and stored in .env - the access token it buys
is requested fresh on first use and cached in memory for the run; nothing is
written back to disk. Scope is `gmail.readonly`: this adapter cannot send,
label, or delete anything, by construction of the token itself.
"""

from __future__ import annotations

import base64
import logging
import time
from datetime import UTC, datetime
from email.utils import parsedate_to_datetime

from ..http import HttpClient

logger = logging.getLogger(__name__)

TOKEN_URL = "https://oauth2.googleapis.com/token"
MESSAGES_URL = "https://gmail.googleapis.com/gmail/v1/users/me/messages"
MESSAGE_URL = "https://gmail.googleapis.com/gmail/v1/users/me/messages/{message_id}"


def _decode(data: str) -> str:
    """Gmail encodes bodies as URL-safe base64, no padding guaranteed."""
    padded = data + "=" * (-len(data) % 4)
    return base64.urlsafe_b64decode(padded).decode("utf-8", errors="replace")


def _extract_body(payload: dict) -> tuple[str, str]:
    """Walks `payload.parts` for the first text/plain and text/html bodies.
    Multipart messages nest arbitrarily (plain text inside an alternative
    inside a mixed part with attachments), so this recurses rather than
    assuming one level."""
    plain = ""
    html = ""
    mime_type = payload.get("mimeType", "")
    body_data = (payload.get("body") or {}).get("data")

    if body_data and mime_type == "text/plain" and not plain:
        plain = _decode(body_data)
    elif body_data and mime_type == "text/html" and not html:
        html = _decode(body_data)

    for part in payload.get("parts") or []:
        child_plain, child_html = _extract_body(part)
        plain = plain or child_plain
        html = html or child_html

    return plain, html


def _header(headers: list[dict], name: str) -> str:
    for header in headers:
        if header.get("name", "").lower() == name.lower():
            return header.get("value", "")
    return ""


class GmailSource:
    """ports.EmailSource implemented against the Gmail REST API."""

    def __init__(
        self, http: HttpClient, *, client_id: str, client_secret: str, refresh_token: str
    ) -> None:
        self.http = http
        self._client_id = client_id
        self._client_secret = client_secret
        self._refresh_token = refresh_token
        self._access_token: str | None = None
        self._access_token_expiry: float = 0.0

    async def _bearer(self) -> dict[str, str]:
        if self._access_token is None or time.monotonic() >= self._access_token_expiry:
            await self._refresh_access_token()
        return {"Authorization": f"Bearer {self._access_token}"}

    async def _refresh_access_token(self) -> None:
        response = await self.http.post(
            TOKEN_URL,
            data={
                "client_id": self._client_id,
                "client_secret": self._client_secret,
                "refresh_token": self._refresh_token,
                "grant_type": "refresh_token",
            },
        )
        payload = response.json()
        self._access_token = payload["access_token"]
        # Refresh a little early so a request started near expiry does not
        # race a token that goes stale mid-flight.
        self._access_token_expiry = time.monotonic() + payload.get("expires_in", 3600) - 60

    async def search(self, query: str, *, max_results: int = 50):
        # Local import: keeps the ports module dependency-free of adapters.
        from ...domain.reply_models import EmailReply

        try:
            headers = await self._bearer()
            listing = await self.http.get_json(
                MESSAGES_URL, params={"q": query, "maxResults": max_results}, headers=headers
            )
        except Exception:  # noqa: BLE001 - a mailbox hiccup must not stop the run
            logger.exception("Gmail search failed")
            return []

        message_ids = [item["id"] for item in listing.get("messages") or []]
        replies: list[EmailReply] = []
        for message_id in message_ids:
            reply = await self._fetch(message_id)
            if reply is not None:
                replies.append(reply)
        return replies

    async def _fetch(self, message_id: str):
        from ...domain.reply_models import EmailReply

        try:
            headers = await self._bearer()
            payload = await self.http.get_json(
                MESSAGE_URL.format(message_id=message_id),
                params={"format": "full"},
                headers=headers,
            )
        except Exception:  # noqa: BLE001 - one unreadable message must not sink the batch
            logger.exception("Gmail: could not read message %s", message_id)
            return None

        message_headers = (payload.get("payload") or {}).get("headers") or []
        plain, html = _extract_body(payload.get("payload") or {})
        body = plain or _strip_html(html)

        return EmailReply(
            message_id=payload["id"],
            thread_id=payload.get("threadId", payload["id"]),
            sender=_header(message_headers, "From"),
            subject=_header(message_headers, "Subject"),
            snippet=payload.get("snippet", ""),
            body=body,
            received_at=_parsed_date(_header(message_headers, "Date")),
        )


def _strip_html(html: str) -> str:
    if not html:
        return ""
    from ..sources.base import clean_text

    return clean_text(html)


def _parsed_date(raw: str) -> datetime:
    if not raw:
        return datetime.now(UTC)
    try:
        return parsedate_to_datetime(raw)
    except (TypeError, ValueError):
        return datetime.now(UTC)
