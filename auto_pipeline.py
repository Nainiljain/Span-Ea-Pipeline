"""
SPAN-EA Auto Pipeline — Version 1.0
====================================
Fully automated end-to-end pipeline that:
  1. Scrapes events from TSA + Google News
  2. Calls Gemini AI to generate titles, blog drafts, categories & dates
  3. Validates URLs (dead link detection)
  4. Pushes all content to Odoo as UNPUBLISHED DRAFTS
  5. Asks you: publish now, publish later, or discard each post

Completely bypasses Google Sheets — no manual steps required.

Usage:
    python auto_pipeline.py                  # Full pipeline
    python auto_pipeline.py --push-only      # Skip scraping, push from local cache
    python auto_pipeline.py --no-confirm     # Auto-publish all drafts without asking

Requirements (install once):
    pip install requests beautifulsoup4

Credentials: reads from .env file in the same folder
"""

import os
import re
import sys
import json
import time
import argparse
import xmlrpc.client
import xml.etree.ElementTree as ET
from datetime import datetime, timedelta
from email.utils import parsedate_to_datetime
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

GEMINI_API_KEY   = os.getenv("GEMINI_API_KEY", "")
ODOO_URL         = os.getenv("ODOO_URL", "").rstrip("/")
ODOO_DB          = os.getenv("ODOO_DB", "")
ODOO_USER        = os.getenv("ODOO_USER", "")
ODOO_PASSWORD    = os.getenv("ODOO_PASSWORD", "")
AI_MODEL         = "gemini-2.0-flash"
REQUEST_TIMEOUT  = 15
ARTICLE_TIMEOUT  = 8
CURRENT_YEAR     = datetime.now().year
CACHE_FILE       = "pipeline_cache.json"

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/122.0.0.0 Safari/537.36"
    ),
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "en-US,en;q=0.9",
}


# ─────────────────────────────────────────────────────────
# SECTION 1: SCRAPERS (TSA + Google News)
# ─────────────────────────────────────────────────────────

def scrape_tsa():
    import requests
    events = []
    print("\n[SCRAPER] TSA (Toronto Society of Architects)...")

    try:
        resp = requests.get(
            "https://torontosocietyofarchitects.ca/events/",
            headers=HEADERS, timeout=REQUEST_TIMEOUT
        )
        if resp.status_code == 200:
            soup = BeautifulSoup(resp.text, "html.parser")
            cards = (
                soup.select("article.type-tribe_events")
                or soup.select("article[class*='event']")
                or soup.select(".tribe-events-calendar article")
            )
            for card in cards[:5]:
                title_tag = card.find("h2") or card.find("h3") or card.find("a")
                link_tag  = card.find("a", href=True)
                desc_tag  = card.find("p")
                title   = title_tag.get_text(strip=True) if title_tag else "TSA Event"
                link    = link_tag["href"] if link_tag else "https://torontosocietyofarchitects.ca/events/"
                content = desc_tag.get_text(strip=True) if desc_tag else title
                if title and link:
                    events.append({"source": "TSA (Toronto Society of Architects)", "title": title, "content": content, "link": link})
                    print(f"  [HTML] {title[:70]}")
    except Exception as e:
        print(f"  TSA HTML error: {e}")

    # RSS fallback
    if not events:
        try:
            for rss_url in ["https://torontosocietyofarchitects.ca/events/feed/", "https://torontosocietyofarchitects.ca/feed/"]:
                resp = requests.get(rss_url, headers=HEADERS, timeout=REQUEST_TIMEOUT)
                if resp.status_code == 200 and "<rss" in resp.text:
                    root = ET.fromstring(resp.text)
                    channel = root.find("channel")
                    for item in (channel.findall("item") if channel else [])[:6]:
                        title = item.findtext("title", "TSA Event")
                        link  = item.findtext("link", "https://torontosocietyofarchitects.ca")
                        desc  = BeautifulSoup(item.findtext("description", ""), "html.parser").get_text(strip=True)
                        events.append({"source": "TSA (Toronto Society of Architects)", "title": title, "content": desc[:500], "link": link})
                        print(f"  [RSS] {title[:70]}")
                    break
        except Exception as e:
            print(f"  TSA RSS error: {e}")

    print(f"  → {len(events)} TSA events found")
    return events


def scrape_google_news(existing_titles=None):
    import requests
    existing_titles = existing_titles or set()
    events = []
    CUTOFF_YEAR = CURRENT_YEAR - 1

    queries = [
        ("OAA Ontario architects events",    "OAA (Ontario Association of Architects)"),
        ("PEO Ontario engineers events",     "PEO (Professional Engineers Ontario)"),
        ("OSPE Ontario engineering events",  "OSPE (Ontario Society of Professional Engineers)"),
    ]

    JUNK_KEYWORDS = ("all events", "upcoming events", "employment", "peo portal",
                     "contact us", "about us", "login", "sign in", "privacy policy",
                     "terms of use", "careers", "forgot password", "search results")

    print("\n[SCRAPER] Google News (OAA / PEO / OSPE)...")

    for query, org_name in queries:
        try:
            rss_url = f"https://news.google.com/rss/search?q={query.replace(' ', '+')}&hl=en-CA&gl=CA&ceid=CA:en"
            resp = requests.get(rss_url, headers=HEADERS, timeout=REQUEST_TIMEOUT)
            if resp.status_code != 200:
                continue
            root    = ET.fromstring(resp.text)
            channel = root.find("channel")
            items   = channel.findall("item") if channel else []
            count   = 0

            for item in items[:15]:
                title = item.findtext("title", "").strip()
                link  = item.findtext("link", "").strip()
                desc  = item.findtext("description", "").strip()
                pub   = item.findtext("pubDate", "").strip()

                if not title or title.lower() in existing_titles:
                    continue
                tl = title.lower()
                if any(junk in tl for junk in JUNK_KEYWORDS):
                    continue
                if "@" in title:
                    continue

                try:
                    pub_dt = parsedate_to_datetime(pub)
                    if pub_dt.year < CUTOFF_YEAR:
                        continue
                    date_str = pub_dt.strftime("%Y-%m-%d")
                except Exception:
                    date_str = ""

                content = BeautifulSoup(desc, "html.parser").get_text(strip=True)
                if date_str:
                    content = f"(News Published: {date_str}) - {content}"

                events.append({
                    "source":  org_name,
                    "title":   title,
                    "content": content[:500],
                    "link":    link,
                })
                existing_titles.add(title.lower())
                print(f"  [{org_name[:4]}] {title[:70]}")
                count += 1
                if count >= 5:
                    break

        except Exception as e:
            print(f"  Google News error ({query}): {e}")

        time.sleep(1)

    print(f"  → {len(events)} news items found")
    return events


# ─────────────────────────────────────────────────────────
# SECTION 2: GEMINI AI PROCESSING
# ─────────────────────────────────────────────────────────

def smart_parse_date(raw):
    if not raw:
        return None
    s = str(raw).strip()
    s = re.sub(r"(\d+)(st|nd|rd|th)", r"\1", s)
    s = re.sub(r"(?:Monday|Tuesday|Wednesday|Thursday|Friday|Saturday|Sunday|Mon|Tue|Wed|Thu|Fri|Sat|Sun),?\s*", "", s, flags=re.IGNORECASE)
    try:
        return datetime.strptime(s, "%B %d, %Y")
    except Exception:
        pass
    try:
        return datetime.strptime(s + f", {CURRENT_YEAR}", "%B %d, %Y")
    except Exception:
        pass
    return None


def call_gemini(title, content, source):
    import requests
    if not GEMINI_API_KEY:
        print("  [AI] ⚠️  No GEMINI_API_KEY — skipping AI enrichment")
        return None

    src = (source or "").lower()
    is_eng  = "peo" in src or "ospe" in src
    is_arch = "tsa" in src or "oaa" in src
    pd_name = "PDH hours (PEO)" if is_eng else ("OAA Structured Learning Hours" if is_arch else "Professional Development Credits")

    prompt = f"""Role: You are SPAN-EA's blog editor. SPAN-EA discovers events from TSA, OAA, PEO, and OSPE and recommends them to newcomer engineers/architects in Ontario. SPAN-EA does NOT organize these events.

Voice: Warm, encouraging, professional — like a mentor recommending something to a newcomer colleague.
Context: Today is {datetime.now().strftime("%B %d, %Y")}. Current year: {CURRENT_YEAR}.
Source: {source}
Credential: {pd_name}

Analyze the article. Return JSON with EXACTLY these fields:
1. "category": "Upcoming Event" OR "Industry News"
2. "eventDate": Real event date like "March 15, 2026". Ignore the news publish date. If none, return "Date TBD".
3. "aiTitle": Catchy blog title (max 10 words). Don't copy original title.
4. "cpdInfo": Only state {pd_name} if explicitly mentioned in source. Otherwise return "Not specified".
5. "blogDraft": 4-5 sentence blog post in SPAN-EA's voice:
   - Sentence 1: What is this, who runs it, when.
   - Sentence 2: Why newcomers in Ontario should care.
   - Sentence 3: Key takeaways (mention credits only if source states them).
   - Sentence 4: Practical details (cost, format, deadline).
   - Sentence 5: Call-to-action. NEVER say "SPAN-EA is hosting".

Title: "{title}"
Content: "{str(content)[:1000]}"

Respond ONLY with valid JSON. No markdown. No extra text."""

    try:
        url = f"https://generativelanguage.googleapis.com/v1beta/models/{AI_MODEL}:generateContent?key={GEMINI_API_KEY}"
        resp = requests.post(url, json={
            "contents": [{"parts": [{"text": prompt}]}],
            "generationConfig": {"temperature": 0.6, "maxOutputTokens": 1024}
        }, timeout=30)

        if resp.status_code != 200:
            print(f"  [AI] HTTP {resp.status_code}")
            return None

        text = resp.json()["candidates"][0]["content"]["parts"][0]["text"].strip()
        match = re.search(r"\{[\s\S]*\}", text)
        if match:
            result = json.loads(match.group(0))
            if result.get("blogDraft") and result.get("category"):
                return result
    except Exception as e:
        print(f"  [AI] Error: {e}")
    return None


def is_url_alive(url):
    import requests
    if not url:
        return False
    try:
        resp = requests.get(url.strip(), headers=HEADERS, timeout=8, allow_redirects=True)
        return 200 <= resp.status_code < 400
    except Exception:
        return False


def enrich_events(raw_events):
    """Run each scraped event through Gemini AI and URL validation."""
    enriched = []
    total = len(raw_events)

    print(f"\n[AI] Processing {total} events with Gemini ({AI_MODEL})...")
    print("     (Rate: ~10 req/min — ~6s between calls)\n")

    for i, ev in enumerate(raw_events, 1):
        title   = ev.get("title", "")
        content = ev.get("content", "")
        source  = ev.get("source", "")
        link    = ev.get("link", "")

        print(f"  [{i}/{total}] {title[:65]}")

        # AI call
        ai = call_gemini(title, content, source)
        if not ai:
            # Fallback: use raw data
            ai = {
                "category":  "Industry News",
                "eventDate": "Date TBD",
                "aiTitle":   title,
                "cpdInfo":   "Not specified",
                "blogDraft": content[:400] or title,
            }
            print(f"         → Using raw data (AI unavailable)")
        else:
            print(f"         → {ai.get('category')} | {ai.get('eventDate')} | \"{ai.get('aiTitle','')[:50]}\"")

        # URL validation
        url_ok = is_url_alive(link)
        if not url_ok:
            print(f"         ⚠️  Dead link detected: {link[:60]}")

        # Date parsing
        event_date = smart_parse_date(ai.get("eventDate"))
        is_upcoming = False
        is_past     = False
        if event_date:
            today = datetime.now().replace(hour=0, minute=0, second=0, microsecond=0)
            delta = (event_date - today).days
            if delta >= 0:
                is_upcoming = True
            else:
                is_past = True

        enriched.append({
            "source":      source,
            "original_title": title,
            "url":         link,
            "url_alive":   url_ok,
            "category":    ai.get("category", "Industry News"),
            "event_date":  ai.get("eventDate", "Date TBD"),
            "ai_title":    ai.get("aiTitle", title),
            "cpd_info":    ai.get("cpdInfo", "Not specified"),
            "blog_draft":  ai.get("blogDraft", content),
            "is_upcoming": is_upcoming,
            "is_past":     is_past,
        })

        # Rate limit guard
        if i < total:
            time.sleep(6)

    return enriched


# ─────────────────────────────────────────────────────────
# SECTION 3: ODOO PUSH + PUBLISH CONFIRMATION
# ─────────────────────────────────────────────────────────

def odoo_connect():
    """Authenticate with Odoo via XML-RPC. Returns (models proxy, uid)."""
    if not ODOO_URL or not ODOO_USER or not ODOO_PASSWORD:
        print("\n[ODOO] ❌ Missing credentials in .env")
        print("  Required: ODOO_URL, ODOO_DB, ODOO_USER, ODOO_PASSWORD")
        sys.exit(1)

    print(f"\n[ODOO] Connecting to {ODOO_URL}...")
    common = xmlrpc.client.ServerProxy(f"{ODOO_URL}/xmlrpc/2/common")
    try:
        version = common.version()
        print(f"  Odoo version: {version.get('server_version', 'unknown')}")
    except Exception as e:
        print(f"  ❌ Cannot connect: {e}")
        sys.exit(1)

    uid = common.authenticate(ODOO_DB, ODOO_USER, ODOO_PASSWORD, {})
    if not uid:
        print("  ❌ Authentication failed — check credentials in .env")
        sys.exit(1)

    print(f"  ✅ Authenticated as UID {uid}")
    models = xmlrpc.client.ServerProxy(f"{ODOO_URL}/xmlrpc/2/object")
    return models, uid


def get_or_create_blog(models, uid):
    blogs = models.execute_kw(ODOO_DB, uid, ODOO_PASSWORD, "blog.blog", "search_read",
                              [[]], {"fields": ["id", "name"], "limit": 1})
    if blogs:
        print(f"  Using blog: '{blogs[0]['name']}' (ID: {blogs[0]['id']})")
        return blogs[0]["id"]
    blog_id = models.execute_kw(ODOO_DB, uid, ODOO_PASSWORD, "blog.blog", "create",
                                [{"name": "Our blog"}])
    print(f"  Created new blog (ID: {blog_id})")
    return blog_id


def get_existing_titles(models, uid):
    posts = models.execute_kw(ODOO_DB, uid, ODOO_PASSWORD, "blog.post", "search_read",
                              [[]], {"fields": ["name"], "limit": 500})
    return {p["name"].strip().lower() for p in posts}


def create_draft(models, uid, blog_id, ev):
    """Create a single blog post in Odoo as an unpublished draft."""
    source_url = ev.get("url", "")
    content_html = (
        f"<p>{ev['blog_draft']}</p>"
        + (f'<p><a href="{source_url}">Read more / Register →</a></p>' if source_url else "")
    )

    post_data = {
        "blog_id":           blog_id,
        "name":              ev["ai_title"],
        "content":           content_html,
        "website_published": False,
    }

    date_obj = smart_parse_date(ev.get("event_date"))
    if date_obj:
        post_data["post_date"] = date_obj.strftime("%Y-%m-%d %H:%M:%S")

    try:
        post_id = models.execute_kw(ODOO_DB, uid, ODOO_PASSWORD, "blog.post", "create", [post_data])
        return post_id
    except Exception as e:
        # Retry without post_date (some Odoo versions block it)
        if "post_date" in post_data:
            del post_data["post_date"]
            try:
                return models.execute_kw(ODOO_DB, uid, ODOO_PASSWORD, "blog.post", "create", [post_data])
            except Exception as e2:
                print(f"    ❌ Failed: {e2}")
        else:
            print(f"    ❌ Failed: {e}")
        return None


def publish_post(models, uid, post_id):
    """Flip website_published = True on an existing draft."""
    try:
        models.execute_kw(ODOO_DB, uid, ODOO_PASSWORD, "blog.post", "write",
                          [[post_id], {"website_published": True}])
        return True
    except Exception as e:
        print(f"    ❌ Publish failed: {e}")
        return False


def push_and_confirm(enriched, models, uid, blog_id, auto_confirm=False):
    """
    For each enriched event:
      - Create the Odoo draft
      - Print a preview
      - Ask: [P]ublish now / [S]ave as draft / [D]iscard
    """
    existing = get_existing_titles(models, uid)

    print("\n" + "=" * 60)
    print("  ODOO PUSH + PUBLISH REVIEW")
    print("=" * 60)

    # Filter out past events and dead links
    pushable = [ev for ev in enriched if not ev["is_past"] and ev["url_alive"]]
    skipped_past = sum(1 for ev in enriched if ev["is_past"])
    skipped_dead = sum(1 for ev in enriched if not ev["url_alive"])

    print(f"\n  Ready to push:   {len(pushable)} posts")
    print(f"  Skipped (past):  {skipped_past}")
    print(f"  Skipped (dead link): {skipped_dead}")

    if not pushable:
        print("\n  No posts to push. Done.")
        return

    created_count   = 0
    published_count = 0
    discarded_count = 0
    skipped_dup     = 0

    for i, ev in enumerate(pushable, 1):
        title_key = ev["ai_title"].strip().lower()
        if title_key in existing:
            print(f"\n  [{i}/{len(pushable)}] ⏭️  DUPLICATE — skipping: {ev['ai_title'][:60]}")
            skipped_dup += 1
            continue

        # ── Print preview ──
        print(f"\n{'─' * 60}")
        print(f"  [{i}/{len(pushable)}] PREVIEW")
        print(f"{'─' * 60}")
        print(f"  Title     : {ev['ai_title']}")
        print(f"  Category  : {ev['category']}")
        print(f"  Event Date: {ev['event_date']}")
        print(f"  Source    : {ev['source']}")
        print(f"  URL       : {ev['url']}")
        print(f"  CPD       : {ev['cpd_info']}")
        print(f"\n  Blog Draft:")
        print(f"  {ev['blog_draft'][:400]}...")
        print()

        if auto_confirm:
            choice = "s"  # Save as draft in auto mode
            print("  [AUTO] Saving as draft...")
        else:
            print("  What would you like to do?")
            print("  [P] Publish now  |  [S] Save as draft  |  [D] Discard")
            choice = input("  Your choice: ").strip().lower()

        if choice == "d":
            print("  ❌ Discarded — not pushed to Odoo.")
            discarded_count += 1
            continue

        # Create the draft in Odoo
        post_id = create_draft(models, uid, blog_id, ev)
        if not post_id:
            continue

        existing.add(title_key)
        created_count += 1

        if choice == "p":
            ok = publish_post(models, uid, post_id)
            if ok:
                print(f"  ✅ Published live! Post ID: {post_id}")
                published_count += 1
            else:
                print(f"  📄 Saved as draft (publish failed). Post ID: {post_id}")
        else:
            print(f"  📄 Saved as draft. Post ID: {post_id}")
            print(f"     → Review at: {ODOO_URL}/odoo/website")

        time.sleep(1)

    # ── Final summary ──
    print(f"\n{'=' * 60}")
    print(f"  PIPELINE COMPLETE")
    print(f"{'=' * 60}")
    print(f"  Posts created   : {created_count}")
    print(f"  Published live  : {published_count}")
    print(f"  Saved as draft  : {created_count - published_count}")
    print(f"  Discarded       : {discarded_count}")
    print(f"  Duplicates skip : {skipped_dup}")
    print(f"  Past events skip: {skipped_past}")
    print(f"  Dead links skip : {skipped_dead}")
    print(f"\n  → Review all drafts: {ODOO_URL}/odoo/website")
    print(f"{'=' * 60}\n")


# ─────────────────────────────────────────────────────────
# SECTION 4: MAIN
# ─────────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(description="SPAN-EA Auto Pipeline")
    parser.add_argument("--push-only",   action="store_true", help="Skip scraping; use cached data from pipeline_cache.json")
    parser.add_argument("--no-confirm",  action="store_true", help="Auto-save all posts as drafts without asking")
    parser.add_argument("--scrape-only", action="store_true", help="Only scrape + enrich, save to cache (don't push to Odoo)")
    args = parser.parse_args()

    print("=" * 60)
    print("  SPAN-EA AUTO PIPELINE")
    print(f"  {datetime.now().strftime('%B %d, %Y  %H:%M')}")
    print("=" * 60)

    # ── Step 1: Scrape ──
    if args.push_only and os.path.exists(CACHE_FILE):
        print(f"\n[CACHE] Loading enriched data from {CACHE_FILE}...")
        with open(CACHE_FILE) as f:
            enriched = json.load(f)
        print(f"  Loaded {len(enriched)} cached items")
    else:
        tsa_events   = scrape_tsa()
        time.sleep(2)
        existing_set = {e["title"] for e in tsa_events}
        news_events  = scrape_google_news(existing_titles=existing_set)
        all_events   = tsa_events + news_events

        print(f"\n[SCRAPER] Total: {len(all_events)} events "
              f"(TSA: {len(tsa_events)} | News: {len(news_events)})")

        if not all_events:
            print("\nNo events found. Check your internet connection and try again.")
            sys.exit(0)

        # ── Step 2: AI Enrichment ──
        enriched = enrich_events(all_events)

        # Save cache for --push-only re-runs
        with open(CACHE_FILE, "w") as f:
            json.dump(enriched, f, indent=2, default=str)
        print(f"\n[CACHE] Saved to {CACHE_FILE}")

    if args.scrape_only:
        print("\n[MODE] --scrape-only: done. Run again without --scrape-only to push to Odoo.")
        sys.exit(0)

    # ── Step 3: Connect to Odoo ──
    models, uid = odoo_connect()
    blog_id     = get_or_create_blog(models, uid)

    # ── Step 4: Push + Confirm ──
    push_and_confirm(enriched, models, uid, blog_id, auto_confirm=args.no_confirm)


if __name__ == "__main__":
    main()