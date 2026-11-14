"""
Two ways to search, chosen automatically:

1. No API key configured (default): queries DuckDuckGo's plain HTML
   results page directly and scrapes titles/snippets/links. No account,
   no key, works out of the box.
2. API key configured in the sidebar settings: uses Brave Search's API
   instead, which tends to be more reliable. If the key field is left
   blank, this path is skipped entirely and step 1 is used.
"""

import re
import requests
from html import unescape
from server import config_store

HEADERS = {"User-Agent": "Mozilla/5.0 (Worky local research assistant)"}

RESULT_BLOCK_RE = re.compile(
    r'<a rel="nofollow" class="result__a" href="(.*?)".*?>(.*?)</a>.*?'
    r'<a class="result__snippet".*?>(.*?)</a>',
    re.DOTALL,
)


def _strip_tags(html: str) -> str:
    return unescape(re.sub(r"<.*?>", "", html)).strip()


def _search_duckduckgo(query: str, max_results: int = 5) -> list[dict]:
    resp = requests.post(
        "https://html.duckduckgo.com/html/",
        data={"q": query},
        headers=HEADERS,
        timeout=10,
    )
    resp.raise_for_status()
    results = []
    for match in RESULT_BLOCK_RE.finditer(resp.text):
        url, title_html, snippet_html = match.groups()
        results.append({
            "title": _strip_tags(title_html),
            "url": url,
            "snippet": _strip_tags(snippet_html),
        })
        if len(results) >= max_results:
            break
    return results


def _search_brave(query: str, api_key: str, max_results: int = 5) -> list[dict]:
    resp = requests.get(
        "https://api.search.brave.com/res/v1/web/search",
        params={"q": query, "count": max_results},
        headers={"X-Subscription-Token": api_key, "Accept": "application/json"},
        timeout=10,
    )
    resp.raise_for_status()
    data = resp.json()
    results = []
    for item in data.get("web", {}).get("results", [])[:max_results]:
        results.append({
            "title": item.get("title", ""),
            "url": item.get("url", ""),
            "snippet": item.get("description", ""),
        })
    return results


def search(query: str, max_results: int = 5) -> list[dict]:
    cfg = config_store.load()
    key = (cfg.get("search_api_key") or "").strip()
    provider = (cfg.get("search_api_provider") or "").strip().lower()

    if key and provider == "brave":
        try:
            return _search_brave(query, key, max_results)
        except Exception:
            pass  # fall through to the no-key path if the API call fails

    try:
        return _search_duckduckgo(query, max_results)
    except Exception as e:
        return [{"title": "Search failed", "url": "", "snippet": str(e)}]


def format_results_for_model(results: list[dict]) -> str:
    if not results:
        return "No search results found."
    lines = ["Web search results:"]
    for i, r in enumerate(results, 1):
        lines.append(f"{i}. {r['title']}\n   {r['url']}\n   {r['snippet']}")
    return "\n".join(lines)
