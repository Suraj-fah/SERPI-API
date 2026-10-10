"""Search established fact-checking sites for evidence about a claim.

Requires the ``google-search-results`` package and ``SERPAPI_API_KEY``. The
function returns the shared Contextify evidence schema and degrades to an empty
list when configuration, the service, or its response is unavailable.
"""

from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any
from urllib.parse import urlparse


_SITES_FILE = Path(__file__).with_name("factcheck_sites.json")
_MAX_RESULTS = 5


def _load_sites() -> list[dict[str, str]]:
    """Read and validate the site registry; malformed files fail closed."""
    try:
        data = json.loads(_SITES_FILE.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return []
    if not isinstance(data, list):
        return []
    return [
        site for site in data
        if isinstance(site, dict)
        and all(isinstance(site.get(key), str) and site[key].strip()
                for key in ("name", "domain", "country"))
    ]


def _serpapi_search(params: dict[str, str]) -> dict[str, Any]:
    """Call SerpApi using its commonly deployed google-search-results client."""
    from serpapi import GoogleSearch  # type: ignore[import-not-found]

    response = GoogleSearch(params).get_dict()
    return response if isinstance(response, dict) else {}


def search_factchecks(claim: str) -> list[dict[str, str]]:
    """Find up to five fact-check articles matching *claim*.

    Searches the configured domains in one Google query using ``site:``
    operators. Each result follows the shared schema: title, link, source,
    date, and snippet. Search and configuration failures return ``[]``.
    """
    if not isinstance(claim, str) or not claim.strip():
        return []
    api_key = os.getenv("SERPAPI_API_KEY", "").strip()
    sites = _load_sites()
    if not api_key or not sites:
        return []

    # Parenthesized OR keeps the site restriction to the approved registry.
    site_query = " OR ".join(f"site:{site['domain']}" for site in sites)
    params = {
        "engine": "google",
        "q": f"{claim.strip()} ({site_query})",
        "api_key": api_key,
        "num": "10",
    }
    try:
        response = _serpapi_search(params)
    except Exception:
        # Missing package, network errors, API errors, and client changes must
        # not take down the main analysis endpoint.
        return []

    if response.get("error"):
        return []
    site_names = {site["domain"].lower(): site["name"] for site in sites}
    evidence: list[dict[str, str]] = []
    seen_links: set[str] = set()
    results = response.get("organic_results", [])
    if not isinstance(results, list):
        return []

    for item in results:
        if not isinstance(item, dict):
            continue
        link = item.get("link")
        title = item.get("title")
        if not isinstance(link, str) or not isinstance(title, str):
            continue
        link = link.strip()
        if not link.startswith(("https://", "http://")) or link in seen_links:
            continue

        hostname = (urlparse(link).hostname or "").lower()
        hostname = hostname.removeprefix("www.")
        source = next(
            (name for domain, name in site_names.items()
             if hostname == domain or hostname.endswith("." + domain)),
            None,
        )
        if source is None:
            # Do not accept results outside the allowlist, even if the query
            # engine returns unrelated matches.
            continue
        date = item.get("date") or item.get("published_date") or ""
        snippet = item.get("snippet") or ""
        evidence.append({
            "title": title.strip(),
            "link": link,
            "source": source,
            "date": str(date).strip(),
            "snippet": str(snippet).strip(),
        })
        seen_links.add(link)
        if len(evidence) == _MAX_RESULTS:
            break
    return evidence
