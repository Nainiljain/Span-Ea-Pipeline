"""
SPAN-EA Scraper — Version 2.0
================================
Scrapes events from TSA + Google News (OAA / PEO / OSPE).

TWO OUTPUT MODES:
  Mode A — Webhook (Original): Sends scraped data to Google Sheets via webhook
  Mode B — Cache   (New):      Saves scraped data to pipeline_cache_raw.json
                                for use by auto_pipeline.py or push_to_odoo.py

Sources:
  - TSA  : Toronto Society of Architects (HTML scrape → RSS fallback)
  - OAA  : Ontario Association of Architects (via Google News RSS)
  - PEO  : Professional Engineers Ontario (via Google News RSS)
  - OSPE : Ontario Society of Professional Engineers (via Google News RSS)

Note: OAA and PEO dropped direct scraping — ASP.NET/WAF bot protection blocks it.
      Google News RSS is used instead as a reliable fallback.

Usage:
    python scrape_events.py                # Auto mode (webhook if configured, else cache)
    python scrape_events.py --webhook      # Force send to Google Sheets webhook
    python scrape_events.py --cache        # Force save to pipeline_cache_raw.json
    python scrape_events.py --dry-run      # Scrape only, print results, save nothing

Requirements:
    pip install requests beautifulsoup4

Credentials (.env):
    SPAN_EA_WEBHOOK_URL=https://script.google.com/macros/s/...
"""

import os
import re
import sys
import json
import time
import argparse
import xml.etree.ElementTree as ET
from datetime import datetime
from email.utils import parsedate_to_datetime

import requests
from bs4 import BeautifulSoup

# ─────────────────────────────────────────────────────────
# SECTION 0: CONFIG — Load from .env
# ─────────────────────────────────────────────────────────

if os.path.exists(".env"):
    with open(".env") as f:
        for line in f:
            line = line.strip()
            if "=" in line and not line.startswith("#"):
                key, value = line.split("=", 1)
                os.environ[key.strip()] = value.strip()

WEBHOOK_URL      = os.getenv("SPAN_EA_WEBHOOK_URL", "")
REQUEST_TIMEOUT  = 15
ARTICLE_TIMEOUT  = 8
CURRENT_YEAR     = datetime.now().year
CACHE_RAW_FILE   = "pipeline_cache_raw.json"

# Browser-like headers to avoid being blocked by bot protection
HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/122.0.0.0 Safari/537.36"
    ),
    "Accept":          "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "en-US,en;q=0.9",
    "Accept-Encoding": "gzip, deflate, br",
    "Connection":      "keep-alive",
}

# Junk titles to skip (navigation pages, portal links, etc.)
JUNK_KEYWORDS = (
    "all events", "upcoming events", "employment opportunities",
    "registration & pricing", "accommodation", "peo portal",
    "contact us", "about us", "login", "sign in", "news & insights",
    "privacy policy", "terms of use", "member directory",
    "forgot password", "search results", "site map", "careers",
    "pricing 2025", "pricing 2026",
)
JUNK_PREFIXES = ("home -", "home |", "am i ", "am i ready")


# ─────────────────────────────────────────────────────────
# SECTION 1: TSA SCRAPER
# Strategy 1 — Scrape HTML event listing
# Strategy 2 — Fallback to WordPress RSS feed
# ─────────────────────────────────────────────────────────

def scrape_tsa():
    """Scrape events from Toronto Society of Architects."""
    events = []
    print("\n[TSA] Scraping Toronto Society of Architects...")

    # ── Strategy 1: HTML event listing ──
    try:
        session = requests.Session()
        resp = session.get(
            "https://torontosocietyofarchitects.ca/events/",
            headers=HEADERS,
            timeout=REQUEST_TIMEOUT,
        )
        print(f"  HTML status: {resp.status_code}")

        if resp.status_code == 200:
            soup = BeautifulSoup(resp.text, "html.parser")

            # Try multiple WordPress/event theme selectors
            event_cards = (
                soup.select("article.tribe_events_cat")
                or soup.select("article.type-tribe_events")
                or soup.select(".tribe-events-calendar article")
                or soup.select(".tribe-event-url")
                or soup.select("article[class*='event']")
                or soup.select(".wp-block-latest-posts__list li")
                or soup.select("h2.tribe-events-list-event-title")
                or soup.select(".events-list .event-item")
            )

            if event_cards:
                for card in event_cards[:5]:
                    title_tag = (
                        card.find("h2")
                        or card.find("h3")
                        or card.find("a")
                        or card.find(class_=lambda c: c and "title" in c.lower() if c else False)
                    )
                    link_tag = card.find("a", href=True)
                    desc_tag = (
                        card.find("p")
                        or card.find(class_=lambda c: c and "description" in c.lower() if c else False)
                        or card.find(class_=lambda c: c and "excerpt" in c.lower() if c else False)
                    )

                    title   = title_tag.get_text(strip=True) if title_tag else "TSA Event"
                    link    = link_tag["href"] if link_tag else "https://torontosocietyofarchitects.ca/events/"
                    content = desc_tag.get_text(strip=True) if desc_tag else title

                    if title and link:
                        print(f"  [HTML] {title[:70]}")
                        events.append({
                            "source":  "TSA (Toronto Society of Architects)",
                            "title":   title,
                            "content": content,
                            "link":    link,
                        })
            else:
                print("  No HTML event cards matched — falling back to RSS...")

        else:
            print(f"  HTML blocked ({resp.status_code}) — trying RSS feed...")

    except Exception as e:
        print(f"  HTML error: {e} — trying RSS feed...")

    # ── Strategy 2: WordPress RSS fallback ──
    if not events:
        try:
            rss_urls = [
                "https://torontosocietyofarchitects.ca/events/feed/",
                "https://torontosocietyofarchitects.ca/feed/",
            ]
            for rss_url in rss_urls:
                resp = requests.get(rss_url, headers=HEADERS, timeout=REQUEST_TIMEOUT)
                print(f"  RSS status ({rss_url}): {resp.status_code}")

                if resp.status_code != 200 or "<rss" not in resp.text:
                    continue

                root    = ET.fromstring(resp.text)
                channel = root.find("channel")
                items   = channel.findall("item") if channel is not None else []
                seen_rss_titles = set()

                for item in items[:10]:
                    title = item.findtext("title", default="TSA Event")
                    link  = item.findtext("link",  default="https://torontosocietyofarchitects.ca")

                    # Prefer content:encoded over description for full body
                    content_encoded = item.findtext(
                        "{http://purl.org/rss/1.0/modules/content/}encoded"
                    )
                    description = item.findtext("description", default="")
                    html_body   = content_encoded if content_encoded else description
                    desc_clean  = BeautifulSoup(html_body, "html.parser").get_text(
                        separator=" ", strip=True
                    )

                    # Try fetching the actual event page to get an exact date
                    extracted_date = ""
                    try:
                        art_resp = requests.get(link, headers=HEADERS, timeout=ARTICLE_TIMEOUT)
                        if art_resp.status_code == 200:
                            art_soup  = BeautifulSoup(art_resp.content, "html.parser")
                            full_text = art_soup.get_text(separator=" ")

                            date_match = re.search(
                                r"(?:January|February|March|April|May|June|July|"
                                r"August|September|October|November|December)"
                                r"\s+\d{1,2}(?:st|nd|rd|th)?,\s+\d{4}",
                                full_text,
                            )
                            if date_match:
                                extracted_date = f"[Exact Date Found by Scraper: {date_match.group(0)}] "

                            # Replace junk RSS summary with real page content
                            if "appeared first on" in desc_clean and len(desc_clean) < 200:
                                paragraphs = art_soup.find_all("p")
                                p_text = " ".join(
                                    p.get_text(strip=True)
                                    for p in paragraphs
                                    if len(p.get_text(strip=True)) > 20
                                )
                                if p_text:
                                    desc_clean = p_text

                    except Exception as page_err:
                        print(f"  Article parse warning ({link}): {page_err}")

                    if extracted_date:
                        desc_clean = extracted_date + desc_clean

                    desc_clean = desc_clean[:800]

                    if title in seen_rss_titles:
                        continue
                    seen_rss_titles.add(title)

                    print(f"  [RSS] {title[:70]}")
                    events.append({
                        "source":  "TSA (Toronto Society of Architects)",
                        "title":   title,
                        "content": desc_clean or title,
                        "link":    link,
                    })

                    if len(events) >= 5:
                        break

                if events:
                    break

        except Exception as e:
            print(f"  RSS error: {e}")

    if not events:
        print("  ⚠️  Could not retrieve TSA events — check site manually.")

    print(f"  → {len(events)} TSA event(s) found")
    return events


# ─────────────────────────────────────────────────────────
# SECTION 2: GOOGLE NEWS SCRAPER
# OAA / PEO / OSPE via Google News RSS
# (Direct scraping blocked by ASP.NET/WAF on those sites)
# ─────────────────────────────────────────────────────────

def scrape_google_news(existing_titles=None):
    """
    Fetch Ontario architecture & engineering news via Google News RSS.
    Only returns articles from the current year or later.
    Pass existing_titles (set) to avoid duplicating TSA events.
    """
    events          = []
    existing_titles = existing_titles or set()
    seen_titles     = {t.strip().lower() for t in existing_titles}
    seen_keys       = set()
    CUTOFF_YEAR     = CURRENT_YEAR

    # Site-specific Google News queries → mapped to real org names
    queries = {
        f"site:oaa.on.ca+after:{CURRENT_YEAR}-01-01":  "OAA (Ontario Association of Architects)",
        f"site:peo.on.ca+after:{CURRENT_YEAR}-01-01":  "PEO (Professional Engineers Ontario)",
        f"site:ospe.on.ca+after:{CURRENT_YEAR}-01-01": "OSPE (Ontario Society of Professional Engineers)",
    }

    print("\n[GOOGLE NEWS] Scraping OAA / PEO / OSPE...")

    for query, org_name in queries.items():
        url = (
            f"https://news.google.com/rss/search"
            f"?q={query}&hl=en-CA&gl=CA&ceid=CA:en"
        )
        try:
            resp = requests.get(url, headers=HEADERS, timeout=REQUEST_TIMEOUT)
            print(f"  [{org_name[:4]}] status: {resp.status_code}")

            if resp.status_code != 200:
                continue

            root    = ET.fromstring(resp.content)
            channel = root.find("channel")
            items   = channel.findall("item") if channel is not None else []

            for item in items[:10]:
                title = item.findtext("title", "").strip()
                link  = item.findtext("link",  "").strip()
                desc  = item.findtext("description", "").strip()
                pub   = item.findtext("pubDate", "").strip()

                # ── Date filter: skip articles older than cutoff year ──
                formatted_date = ""
                if pub:
                    try:
                        pub_dt = parsedate_to_datetime(pub)
                        formatted_date = pub_dt.strftime("%Y-%m-%d")
                        if pub_dt.year < CUTOFF_YEAR:
                            continue
                    except Exception:
                        formatted_date = pub

                # ── Junk filters ──
                if not title:
                    continue
                title_lower = title.lower()
                is_email_junk = "@" in title and "." in title
                if (
                    is_email_junk
                    or any(junk in title_lower for junk in JUNK_KEYWORDS)
                    or any(title_lower.startswith(p) for p in JUNK_PREFIXES)
                ):
                    continue

                # ── Deduplicate ──
                dedupe_key = f"{title_lower}|{link}"
                if title_lower in seen_titles or dedupe_key in seen_keys:
                    continue
                seen_titles.add(title_lower)
                seen_keys.add(dedupe_key)

                # ── Strip HTML from description ──
                desc = BeautifulSoup(desc, "html.parser").get_text(separator=" ", strip=True)

                # Label the publish date so AI doesn't confuse it with the event date
                base_content = (
                    f"(News Published: {formatted_date}) - {desc}"
                    if formatted_date else desc
                )
                content = base_content

                # Try fetching the full article for richer content
                try:
                    if "news.google.com" not in link:
                        art_resp = requests.get(
                            link, headers=HEADERS,
                            timeout=ARTICLE_TIMEOUT, allow_redirects=True
                        )
                        if art_resp.status_code == 200:
                            art_soup   = BeautifulSoup(art_resp.content, "html.parser")
                            paragraphs = art_soup.find_all("p")
                            p_text = " ".join(
                                p.get_text(strip=True) for p in paragraphs
                                if len(p.get_text(strip=True)) > 20
                            )
                            if p_text and len(p_text) > 50:
                                content = p_text[:1500]
                                if formatted_date:
                                    content = f"[{formatted_date}] {content}"
                except Exception as article_err:
                    print(f"  Article fetch warning ({link}): {article_err}")

                content = content or title

                print(f"  [{org_name[:4]}] {title[:70]}")
                events.append({
                    "source":  org_name,
                    "title":   title,
                    "content": content[:500],
                    "link":    link,
                })

                if len(events) >= 8:
                    break

        except Exception as e:
            print(f"  Google News error for '{org_name}': {e}")

        time.sleep(1)

    if not events:
        print(f"  ⚠️  No Google News items found for {CURRENT_YEAR}.")

    print(f"  → {len(events)} news item(s) found")
    return events


# ─────────────────────────────────────────────────────────
# SECTION 3: OUTPUT MODES
# ─────────────────────────────────────────────────────────

def send_to_webhook(all_events):
    """
    Mode A — Send scraped events to Google Sheets via Apps Script webhook.
    The webhook URL is set in .env as SPAN_EA_WEBHOOK_URL.
    """
    if not all_events:
        print("\n[WEBHOOK] No events to send.")
        return False

    if not WEBHOOK_URL.startswith("http"):
        print("\n[WEBHOOK] ⚠️  SPAN_EA_WEBHOOK_URL not configured in .env")
        print("  Set it to your Google Apps Script deployment URL.")
        return False

    print(f"\n[WEBHOOK] Sending {len(all_events)} event(s) to Google Sheets...")

    payload = {"data": all_events}
    headers = {"Content-Type": "application/json"}

    for attempt in range(1, 4):
        try:
            response = requests.post(
                WEBHOOK_URL,
                data=json.dumps(payload),
                headers=headers,
                timeout=REQUEST_TIMEOUT,
            )
            if response.status_code == 200:
                print(f"  ✅ Sent successfully!")
                print(f"  Response: {response.text[:200]}")
                return True

            print(f"  ❌ Attempt {attempt}/3 failed — HTTP {response.status_code}")
            print(f"  Response: {response.text[:200]}")

        except Exception as e:
            print(f"  ❌ Attempt {attempt}/3 connection error: {e}")

        if attempt < 3:
            time.sleep(2)

    print("  ❌ Failed to send after 3 attempts.")
    return False


def save_to_cache(all_events):
    """
    Mode B — Save scraped events to pipeline_cache_raw.json.
    auto_pipeline.py reads this file for AI enrichment + Odoo push.
    """
    if not all_events:
        print("\n[CACHE] No events to save.")
        return False

    with open(CACHE_RAW_FILE, "w", encoding="utf-8") as f:
        json.dump(all_events, f, indent=2, ensure_ascii=False)

    print(f"\n[CACHE] ✅ Saved {len(all_events)} event(s) to {CACHE_RAW_FILE}")
    print(f"  Next step: python auto_pipeline.py --push-only")
    print(f"         or: python push_to_odoo.py --cache")
    return True


def print_dry_run(all_events):
    """Dry run — print all scraped events to terminal without saving."""
    print(f"\n[DRY RUN] {len(all_events)} event(s) scraped:")
    print("=" * 60)
    for i, ev in enumerate(all_events, 1):
        print(f"\n  [{i}] {ev['title']}")
        print(f"       Source : {ev['source']}")
        print(f"       Link   : {ev['link']}")
        print(f"       Content: {ev['content'][:120]}...")
    print("=" * 60)
    print("  [DRY RUN] Nothing was saved or sent.")


# ─────────────────────────────────────────────────────────
# SECTION 4: MAIN
# ─────────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(description="SPAN-EA Scraper v2.0")
    mode_group = parser.add_mutually_exclusive_group()
    mode_group.add_argument("--webhook",  action="store_true",
                            help="Send results to Google Sheets webhook")
    mode_group.add_argument("--cache",    action="store_true",
                            help=f"Save results to {CACHE_RAW_FILE}")
    mode_group.add_argument("--dry-run",  action="store_true",
                            help="Print results only, save nothing")
    args = parser.parse_args()

    print("=" * 60)
    print("  SPAN-EA SCRAPER  v2.0")
    print(f"  {datetime.now().strftime('%B %d, %Y  %H:%M')}")
    print(f"  Sources: TSA | Google News (OAA / PEO / OSPE)")
    print("=" * 60)

    # ── Scrape all sources ──
    tsa_events = scrape_tsa()
    time.sleep(2)

    existing = {e["title"] for e in tsa_events}
    gnews_events = scrape_google_news(existing_titles=existing)

    all_events = tsa_events + gnews_events

    print(f"\n[SUMMARY] Total scraped: {len(all_events)}")
    print(f"  TSA: {len(tsa_events)}  |  Google News: {len(gnews_events)}")

    if not all_events:
        print("\n  No events found. Check your internet connection and try again.")
        sys.exit(0)

    # ── Output mode ──
    if args.dry_run:
        print_dry_run(all_events)

    elif args.webhook:
        send_to_webhook(all_events)

    elif args.cache:
        save_to_cache(all_events)

    else:
        # Auto-detect: webhook if configured, else cache
        if WEBHOOK_URL.startswith("http"):
            print("\n  Auto-mode: WEBHOOK detected — sending to Google Sheets...")
            sent = send_to_webhook(all_events)
            if not sent:
                print("  Falling back to cache save...")
                save_to_cache(all_events)
        else:
            print("\n  Auto-mode: No webhook — saving to local cache...")
            save_to_cache(all_events)

    print("\n  Done.\n")


if __name__ == "__main__":
    main()