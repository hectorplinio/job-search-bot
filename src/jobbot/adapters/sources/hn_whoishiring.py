"""Hacker News "Who is hiring?", through the Algolia API HN itself runs on.

No key needed. Each month a new "Ask HN: Who is hiring? (Month Year)" story
collects its postings as top-level comments, each one free text written by
whoever is hiring - no structured fields at all, unlike every other source
here. The company and role live in the first line; the rest is the pitch.

Known limitations, stated rather than hidden:

- Splitting "Company — Role" out of free text is a heuristic, not a parse.
  When a poster does not follow the usual "Company | Role | Location | tags"
  shape, the title ends up being the whole first line and the company field
  stays empty. Still enough to score and to read before clicking through.
- Region is NOT filtered here with an accept-list (Europe/Worldwide/Spain):
  most posts never state a region at all, and rejecting everything that does
  not explicitly say so would drop plenty of genuinely open postings. The
  shared blocklist in config.yaml's `exclude.description` ("us only", "must
  be based in the united states"...) already runs against every source,
  this one included, and catches the clear cases without that risk.
"""

from __future__ import annotations

import html
import logging
import re

from ...domain.criteria import Criteria
from ...domain.models import JobOffer
from ...domain.scoring import contains_term
from .base import BaseSource, clean_text, detect_work_mode

logger = logging.getLogger(__name__)

SEARCH_URL = "https://hn.algolia.com/api/v1/search_by_date"
ITEM_URL = "https://hn.algolia.com/api/v1/items/{item_id}"
THREAD_TITLE_PREFIX = "ask hn: who is hiring?"

# The usual separators between "Company" and the rest of the pitch. Longer,
# more specific ones first so "Company | Role (Remote)" does not get cut at
# the parenthesis before the pipe is tried.
_SEPARATORS = (" | ", " — ", " – ", " - ", ": ")


class HackerNewsSource(BaseSource):
    name = "hn_whoishiring"

    async def search(self, criteria: Criteria) -> list[JobOffer]:
        thread_id = await self._current_thread_id()
        if thread_id is None:
            logger.info("HN: no 'Who is hiring?' thread found")
            return []

        payload = await self.http.get_json(ITEM_URL.format(item_id=thread_id))
        comments = payload.get("children") or []

        terms = criteria.keywords.required_any
        offers: list[JobOffer] = []

        for comment in comments:
            offer = self._to_offer(comment, thread_id)
            if offer is None:
                continue
            if not any(contains_term(offer.searchable_text, term) for term in terms):
                continue
            offers.append(offer)

        return offers[: criteria.search.max_results_per_source]

    async def _current_thread_id(self) -> int | None:
        """The newest "Who is hiring?" story - not "Who wants to be hired?",
        which is candidates, not postings."""
        payload = await self.http.get_json(SEARCH_URL, params={"tags": "story,author_whoishiring"})
        for hit in payload.get("hits") or []:
            title = (hit.get("title") or "").strip().lower()
            if title.startswith(THREAD_TITLE_PREFIX):
                return hit.get("objectID")
        return None

    def _to_offer(self, comment: dict, thread_id: int) -> JobOffer | None:
        raw_text = comment.get("text")
        comment_id = comment.get("id")
        if not raw_text or not comment_id:
            return None  # dead/deleted comments carry no text

        # HN text is HTML with numeric entities (&#x2F; for "/", etc.) and
        # <p> paragraph breaks instead of newlines. The heading sits before
        # the first <p>, outside any tag, so it is split on the tag itself:
        # looking for <p> elements lost it with current lxml, which leaves
        # that leading text out of every paragraph.
        chunks = re.split(r"<p>", raw_text, flags=re.IGNORECASE)
        paragraphs = [text for text in (html.unescape(clean_text(c)) for c in chunks) if text]
        if not paragraphs:
            return None
        first_line = paragraphs[0]
        full_text = " ".join(paragraphs)

        company, _, rest = self._split_heading(first_line)

        return JobOffer(
            source=self.name,
            external_id=f"hn:{comment_id}",
            title=rest or first_line,
            company=company,
            url=f"https://news.ycombinator.com/item?id={comment_id}",
            description=full_text,
            location=first_line,  # the restriction text, when there is one, lives here
            work_mode=detect_work_mode(first_line),
        )

    @staticmethod
    def _split_heading(first_line: str) -> tuple[str, str, str]:
        for sep in _SEPARATORS:
            if sep in first_line:
                company, _, rest = first_line.partition(sep)
                return company.strip(), sep, rest.strip()
        return "", "", first_line
