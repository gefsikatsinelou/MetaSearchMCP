"""Cross-provider relevance ranking and consensus-based result ordering.

When several search providers return overlapping results, the raw output of
the orchestrator is ordered by provider priority rather than by how relevant
or how widely corroborated each result actually is. This module adds an
optional, opt-in re-ranking pass that:

* **Consensus boost** — a result surfaced by multiple independent providers is
  likely more authoritative, so it receives a bonus proportional to how many
  distinct providers returned it.
* **Query relevance** — a result whose title or URL contains an exact whole-word
  match for one of the query terms scores higher than one that merely happens
  to ship early in a provider's response.
* **Stability** — input (provider-priority) order is preserved as a tiebreaker,
  so results that score equally keep their original relative ordering. This
  keeps the output deterministic and never jumps the top provider's result.

The ranking is deliberately lightweight: it only combines signals already
present in the normalized ``SearchHit`` objects and never performs extra
network calls.
"""

from __future__ import annotations

import re
from collections import Counter
from typing import TYPE_CHECKING

from metasearchmcp.merge import canonicalize_url

if TYPE_CHECKING:
    from metasearchmcp.contracts import SearchHit

# A term matches only when it appears as a full word (case-insensitive), so
# e.g. querying "react" does not treat the substring inside "reactive" as a hit.
_WORD_BOUNDARY_RE = re.compile(r"[^\w-]+")

# Score weight for each additional provider that independently returned the
# same canonical result. Boosts corroborated results without overwhelming the
# top-ranked single-provider result.
_CONSENSUS_WEIGHT = 2.0

# Score weight for each query term appearing verbatim in the title or URL.
_TERM_WEIGHT = 1.0


def _tokenize(text: str) -> set[str]:
    """Split *text* into lowercased alphabetic word tokens."""
    return {t for t in _WORD_BOUNDARY_RE.split(text.lower()) if t}


def count_consensus(merged_hits: list[SearchHit]) -> dict[str, int]:
    """Map each canonical URL to how many raw hits point at it.

    ``SearchHit`` objects already carry their ``provider`` name, so two hits
    from the same provider count twice toward the consensus total. That is
    intentional: a provider returning the same URL several times is also weak
    corroboration, but in practice providers return each URL at most once.
    """
    counts: Counter[str] = Counter()
    for hit in merged_hits:
        key = canonicalize_url(hit.url)
        if key:
            counts[key] += 1
    return dict(counts)


def _hit_score(
    hit: SearchHit,
    consensus: int,
    query_terms: set[str],
) -> float:
    """Compute a composite relevance score for a single hit."""
    score = float(consensus) * _CONSENSUS_WEIGHT
    text = f"{hit.title}\n{hit.url}"
    tokens = _tokenize(text)
    score += len(tokens & query_terms) * _TERM_WEIGHT
    return score


def rank_and_dedup_results(
    merged_hits: list[SearchHit],
    query: str,
    max_results: int,
) -> list[SearchHit]:
    """Deduplicate *merged_hits* and order by consensus + query relevance.

    Duplicates (same canonical URL) are collapsed keeping the first
    occurrence, matching the behaviour of ``collapse_duplicate_hits`` in
    :mod:`metasearchmcp.merge`. The remaining unique hits are then scored and
    sorted by descending score, with the original input order used as a stable
    tiebreaker. The result is capped at *max_results*.

    When ``max_results <= 0`` the full (uncapped) list is returned.
    """
    consensus = count_consensus(merged_hits)
    query_terms = _tokenize(query)

    # Keep the first hit per canonical URL while remembering its input index.
    seen: set[str] = set()
    unique: list[tuple[int, SearchHit]] = []
    for index, hit in enumerate(merged_hits):
        key = canonicalize_url(hit.url)
        if key and key not in seen:
            seen.add(key)
            unique.append((index, hit))

    unique.sort(
        key=lambda item: (
            -_hit_score(
                item[1], consensus.get(canonicalize_url(item[1].url), 0), query_terms
            ),
            item[0],
        ),
    )

    ranked = [hit for _, hit in unique]
    if max_results > 0:
        return ranked[:max_results]
    return ranked


def rank_results(
    hits: list[SearchHit],
    query: str,
) -> list[SearchHit]:
    """Reorder an already-deduplicated list of *hits* by relevance to *query*.

    Unlike :func:`rank_and_dedup_results`, this helper does not deduplicate
    (callers that have already collapsed duplicates can use it directly). It
    re-ranks using the same scoring signals: consensus (how many of the
    original pre-dedup hits pointed at the same canonical URL) and query-term
    relevance. The input order is preserved as a stable tiebreaker.
    """
    if not hits:
        return hits
    consensus = count_consensus(hits)
    query_terms = _tokenize(query)
    ranked = [(i, hit) for i, hit in enumerate(hits)]
    ranked.sort(
        key=lambda item: (
            -_hit_score(
                item[1], consensus.get(canonicalize_url(item[1].url), 0), query_terms
            ),
            item[0],
        ),
    )
    return [hit for _, hit in ranked]
