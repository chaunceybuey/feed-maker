#!/usr/bin/env python3
"""
Feed Forge - simple edition.
Reads feeds.json, scrapes each URL, writes RSS XML files to feeds/.

Run locally:  python scrape.py
Run on schedule: GitHub Action (see .github/workflows/scrape.yml)

Install deps: pip install requests beautifulsoup4
"""

import json
import os
import re
import hashlib
import datetime
from urllib.parse import urljoin, urlparse
from collections import Counter

import requests
from bs4 import BeautifulSoup

FEEDS_FILE = "feeds.json"
OUTPUT_DIR = "feeds"

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36",
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "en-US,en;q=0.9",
}


# ── Fetch ─────────────────────────────────────────────────────────────────────

def fetch(url: str) -> BeautifulSoup:
    """Fetch a URL and return a BeautifulSoup object."""
    origin = "{0.scheme}://{0.netloc}".format(urlparse(url))
    hdrs = {**HEADERS, "Referer": origin}
    # Pass raw bytes to BS4 so it reads <meta charset> directly — no encoding guessing
    resp = requests.get(url, headers=hdrs, timeout=15)
    resp.raise_for_status()
    return BeautifulSoup(resp.content, "html.parser")


# ── Auto-detection ────────────────────────────────────────────────────────────

CANDIDATE_TAGS = ["article", "li", "div", "tr"]

def auto_detect(soup: BeautifulSoup, base_url: str) -> list[dict]:
    """
    Find repeating elements that each contain a link + heading.
    Returns a list of {title, link, desc, date} dicts.
    
    Strategy: score every element class that appears 3+ times and
    contains both an <a> and a heading tag. Pick the highest scorer.
    """
    candidates = []

    for tag in CANDIDATE_TAGS:
        # Count how often each class appears on this tag
        class_counts = Counter()
        for el in soup.find_all(tag):
            for cls in el.get("class", []):
                class_counts[cls] += 1

        for cls, count in class_counts.items():
            if count < 3:
                continue
            elements = soup.find_all(tag, class_=cls)
            # Check if most of them have a link and a heading
            with_link_and_heading = sum(
                1 for el in elements
                if el.find("a", href=True) and el.find(re.compile(r"^h[1-6]$"))
            )
            if with_link_and_heading >= max(3, count * 0.6):
                score = with_link_and_heading * count
                candidates.append((score, tag, cls, elements))

    if not candidates:
        return []

    # Use the highest-scoring candidate
    candidates.sort(reverse=True)
    _, _, _, elements = candidates[0]

    return [extract_item(el, base_url) for el in elements]


def extract_item(el, base_url: str) -> dict:
    """Pull title, link, description, and date out of a single element."""
    # Title: prefer heading tags, fall back to any link text
    title = ""
    heading = el.find(re.compile(r"^h[1-6]$"))
    if heading:
        title = heading.get_text(strip=True)
    if not title:
        a = el.find("a", href=True)
        if a:
            title = a.get_text(strip=True)

    # Link: find the <a> nearest to the heading, or the first substantial one
    link = ""
    if heading:
        a = heading.find("a", href=True) or heading.find_next("a", href=True)
    else:
        a = el.find("a", href=True)
    if a:
        link = urljoin(base_url, a["href"])
        # Skip anchors, javascript:, mailto:
        if not link.startswith("http"):
            link = ""

    # Description: first <p> that isn't inside the heading
    desc = ""
    for p in el.find_all("p"):
        text = p.get_text(strip=True)
        if text and text != title and len(text) > 20:
            desc = text
            break

    # Date: look for <time datetime="..."> or common date class patterns
    date = find_date(el)

    return {"title": title, "link": link, "desc": desc, "date": date}


def find_date(el) -> str:
    """Return an RFC-822 date string if a date element is found, else empty string."""
    for sel in ["time[datetime]", "time", "[class*='date']", "[class*='time']",
                "[class*='publish']", "[class*='posted']", "[class*='timestamp']"]:
        node = el.select_one(sel)
        if not node:
            continue
        raw = node.get("datetime", "") or node.get_text(strip=True)
        if not raw:
            continue
        # Try ISO format (most common in datetime attributes)
        try:
            dt = datetime.datetime.fromisoformat(raw[:19].replace("Z", ""))
            return dt.strftime("%a, %d %b %Y %H:%M:%S +0000")
        except Exception:
            pass
    return ""


# ── Manual selector ───────────────────────────────────────────────────────────

def manual_extract(soup: BeautifulSoup, base_url: str, config: dict) -> list[dict]:
    """
    Use explicit CSS selectors from feeds.json.
    Only the container selector is required; title/link are guessed if omitted.
    """
    containers = soup.select(config["selector"])
    items = []
    for el in containers:
        item = extract_item(el, base_url)
        # Allow overrides for individual fields
        if config.get("title_sel"):
            t = el.select_one(config["title_sel"])
            if t:
                item["title"] = t.get_text(strip=True)
        if config.get("link_sel"):
            l = el.select_one(config["link_sel"])
            if l:
                href = l.get("href", "") or (l.find("a") or {}).get("href", "")
                if href:
                    item["link"] = urljoin(base_url, href)
        items.append(item)
    return items


# ── RSS builder ───────────────────────────────────────────────────────────────

def xml_escape(s: str) -> str:
    return s.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;").replace('"', "&quot;")


def build_rss(name: str, url: str, items: list[dict]) -> str:
    now = datetime.datetime.utcnow().strftime("%a, %d %b %Y %H:%M:%S +0000")
    lines = [
        '<?xml version="1.0" encoding="UTF-8"?>',
        '<rss version="2.0" xmlns:dc="http://purl.org/dc/elements/1.1/">',
        "<channel>",
        f"  <title>{xml_escape(name)}</title>",
        f"  <link>{xml_escape(url)}</link>",
        f"  <description>Generated by Feed Forge</description>",
        f"  <lastBuildDate>{now}</lastBuildDate>",
    ]

    seen = set()
    count = 0
    for item in items:
        if not item["title"] or not item["link"]:
            continue
        if item["link"] in seen:
            continue
        seen.add(item["link"])

        guid = hashlib.md5(item["link"].encode()).hexdigest()
        pub = item["date"] or now

        lines += [
            "  <item>",
            f"    <title>{xml_escape(item['title'])}</title>",
            f"    <link>{xml_escape(item['link'])}</link>",
            f"    <guid isPermaLink='false'>{guid}</guid>",
            f"    <pubDate>{pub}</pubDate>",
        ]
        if item["desc"]:
            lines.append(f"    <description>{xml_escape(item['desc'])}</description>")
        lines.append("  </item>")
        count += 1

    lines += ["</channel>", "</rss>"]
    return "\n".join(lines), count


# ── Main ──────────────────────────────────────────────────────────────────────

def safe_filename(name: str) -> str:
    return re.sub(r"[^a-zA-Z0-9]", "_", name).strip("_").lower()


def main():
    if not os.path.exists(FEEDS_FILE):
        print(f"No {FEEDS_FILE} found. Create one first (see README).")
        return

    with open(FEEDS_FILE) as f:
        feeds = json.load(f)

    os.makedirs(OUTPUT_DIR, exist_ok=True)
    results = []

    for feed in feeds:
        name = feed["name"]
        url = feed["url"]
        print(f"Scraping: {name} ({url})")

        try:
            soup = fetch(url)

            if feed.get("selector"):
                items = manual_extract(soup, url, feed)
                method = "manual"
            else:
                items = auto_detect(soup, url)
                method = "auto"

            if not items:
                print(f"  ⚠️  No items found — try adding a 'selector' to feeds.json")
                results.append({"name": name, "ok": False, "count": 0})
                continue

            rss, count = build_rss(name, url, items)
            filename = safe_filename(name) + ".xml"
            path = os.path.join(OUTPUT_DIR, filename)

            with open(path, "w", encoding="utf-8") as f:
                f.write(rss)

            print(f"  ✅  {count} items → {path} ({method})")
            results.append({"name": name, "ok": True, "count": count, "file": filename})

        except Exception as e:
            print(f"  ❌  Failed: {e}")
            results.append({"name": name, "ok": False, "error": str(e)})

    # Summary
    ok = sum(1 for r in results if r["ok"])
    print(f"\nDone: {ok}/{len(results)} feeds updated.")


if __name__ == "__main__":
    main()
