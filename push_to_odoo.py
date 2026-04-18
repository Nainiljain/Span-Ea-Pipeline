"""
SPAN-EA Odoo Push Script — Version 2.0
========================================
Pushes content to Odoo in TWO modes:

  MODE A — Cache Mode (New): Reads pipeline_cache.json from auto_pipeline.py
  MODE B — CSV Mode (Old):   Reads Events.csv + News.html exported from Google Sheet

Features:
  - Creates all posts as UNPUBLISHED DRAFTS
  - Asks you per post: Publish now / Save as draft / Discard
  - Skips duplicates (checks existing Odoo posts by title)
  - Skips past events and dead links automatically
  - Newsletter page update supported (Mode B only)
  - Cleanup flag to unpublish old posts

Usage:
    python push_to_odoo.py                        # Auto-detect mode (cache first, CSV fallback)
    python push_to_odoo.py --cache                # Force Mode A: use pipeline_cache.json
    python push_to_odoo.py --csv                  # Force Mode B: use Events.csv + News.html
    python push_to_odoo.py --no-confirm           # Save all as drafts without asking
    python push_to_odoo.py --publish-all          # Publish everything live without asking
    python push_to_odoo.py --csv --cleanup        # Mode B + unpublish past events
    python push_to_odoo.py --csv --blog-only      # Mode B: skip newsletter
    python push_to_odoo.py --csv --newsletter-only # Mode B: only update newsletter

Requirements:
    - .env file with Odoo credentials
    - pipeline_cache.json (for Mode A) OR Events.csv + News.html (for Mode B)

Credentials (.env):
    ODOO_URL=https://your-site.odoo.com
    ODOO_DB=your-database-name
    ODOO_USER=your-email@example.com
    ODOO_PASSWORD=your-password-or-api-key
"""

import os
import re
import sys
import csv
import json
import time
import argparse
import xmlrpc.client
from datetime import datetime

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

ODOO_URL           = os.getenv("ODOO_URL", "").rstrip("/")
ODOO_DB            = os.getenv("ODOO_DB", "")
ODOO_USER          = os.getenv("ODOO_USER", "")
ODOO_PASSWORD      = os.getenv("ODOO_PASSWORD", "")
CSV_FILE           = os.getenv("CSV_FILE", "Events.csv")
NEWSLETTER_FILE    = os.getenv("NEWSLETTER_FILE", "News.html")
NEWSLETTER_PAGE_URL = os.getenv("NEWSLETTER_PAGE_URL", "/newsletter")
CACHE_FILE         = "pipeline_cache.json"


# ─────────────────────────────────────────────────────────
# SECTION 1: ODOO CONNECTION
# ─────────────────────────────────────────────────────────

def authenticate():
    """Authenticate with Odoo via XML-RPC. Returns (models proxy, uid)."""
    if not ODOO_URL or not ODOO_USER or not ODOO_PASSWORD:
        print("\n❌ Missing Odoo credentials in .env")
        print("   Required keys: ODOO_URL, ODOO_DB, ODOO_USER, ODOO_PASSWORD")
        sys.exit(1)

    print(f"\n[ODOO] Connecting to {ODOO_URL}...")
    common = xmlrpc.client.ServerProxy(f"{ODOO_URL}/xmlrpc/2/common")

    try:
        version = common.version()
        print(f"  Odoo version : {version.get('server_version', 'unknown')}")
    except Exception as e:
        print(f"  ❌ Cannot connect to Odoo: {e}")
        print(f"  Check your ODOO_URL in .env")
        sys.exit(1)

    uid = common.authenticate(ODOO_DB, ODOO_USER, ODOO_PASSWORD, {})
    if not uid:
        print("  ❌ Authentication failed — check ODOO_USER and ODOO_PASSWORD in .env")
        sys.exit(1)

    print(f"  ✅ Authenticated (UID: {uid})")
    models = xmlrpc.client.ServerProxy(f"{ODOO_URL}/xmlrpc/2/object")
    return models, uid


def get_or_create_blog(models, uid):
    """Find the first blog or create one named 'Our blog'."""
    blogs = models.execute_kw(
        ODOO_DB, uid, ODOO_PASSWORD,
        "blog.blog", "search_read",
        [[]], {"fields": ["id", "name"], "limit": 1}
    )
    if blogs:
        print(f"  Blog         : '{blogs[0]['name']}' (ID: {blogs[0]['id']})")
        return blogs[0]["id"]

    blog_id = models.execute_kw(
        ODOO_DB, uid, ODOO_PASSWORD,
        "blog.blog", "create",
        [{"name": "Our blog"}]
    )
    print(f"  Blog created : 'Our blog' (ID: {blog_id})")
    return blog_id


def get_existing_titles(models, uid):
    """Return a set of lowercase post titles already in Odoo (for duplicate check)."""
    posts = models.execute_kw(
        ODOO_DB, uid, ODOO_PASSWORD,
        "blog.post", "search_read",
        [[]], {"fields": ["id", "name", "website_published"], "limit": 500}
    )
    return {p["name"].strip().lower(): p for p in posts}


# ─────────────────────────────────────────────────────────
# SECTION 2: SHARED HELPERS
# ─────────────────────────────────────────────────────────

def smart_parse_date(raw):
    """Parse messy date strings into datetime objects."""
    if not raw:
        return None
    s = str(raw).strip()
    s = re.sub(r"(\d+)(st|nd|rd|th)", r"\1", s)
    s = re.sub(
        r"(?:Monday|Tuesday|Wednesday|Thursday|Friday|Saturday|Sunday|Mon|Tue|Wed|Thu|Fri|Sat|Sun),?\s*",
        "", s, flags=re.IGNORECASE
    )
    for fmt in ("%B %d, %Y", "%Y-%m-%d %H:%M:%S", "%Y-%m-%d"):
        try:
            return datetime.strptime(s.strip(), fmt)
        except ValueError:
            pass
    # Try appending current year for "May 10" style
    try:
        return datetime.strptime(s + f", {datetime.now().year}", "%B %d, %Y")
    except ValueError:
        pass
    return None


def create_draft(models, uid, blog_id, title, content_html, event_date_str=None):
    """
    Create a single blog post as an unpublished draft in Odoo.
    Returns the new post ID, or None on failure.
    """
    post_data = {
        "blog_id":           blog_id,
        "name":              title,
        "content":           content_html,
        "website_published": False,
    }

    date_obj = smart_parse_date(event_date_str)
    if date_obj:
        post_data["post_date"] = date_obj.strftime("%Y-%m-%d %H:%M:%S")

    try:
        return models.execute_kw(
            ODOO_DB, uid, ODOO_PASSWORD,
            "blog.post", "create", [post_data]
        )
    except Exception:
        # Retry without post_date — some Odoo versions reject it via external API
        post_data.pop("post_date", None)
        try:
            return models.execute_kw(
                ODOO_DB, uid, ODOO_PASSWORD,
                "blog.post", "create", [post_data]
            )
        except Exception as e2:
            print(f"    ❌ Failed to create draft: {e2}")
            return None


def publish_post(models, uid, post_id):
    """Set website_published = True for a given post ID."""
    try:
        models.execute_kw(
            ODOO_DB, uid, ODOO_PASSWORD,
            "blog.post", "write",
            [[post_id], {"website_published": True}]
        )
        return True
    except Exception as e:
        print(f"    ❌ Publish failed: {e}")
        return False


def ask_user(title, preview_text, no_confirm=False, publish_all=False):
    """
    Show a preview and ask the user what to do.
    Returns: 'p' (publish), 's' (save draft), 'd' (discard)
    """
    print(f"\n{'─' * 60}")
    print(f"  PREVIEW: {title}")
    print(f"{'─' * 60}")
    print(f"  {preview_text[:350]}...")
    print()

    if publish_all:
        print("  [AUTO --publish-all] Publishing live...")
        return "p"
    if no_confirm:
        print("  [AUTO --no-confirm] Saving as draft...")
        return "s"

    print("  What would you like to do?")
    print("  [P] Publish now  |  [S] Save as draft  |  [D] Discard")
    return input("  Your choice: ").strip().lower()


# ─────────────────────────────────────────────────────────
# SECTION 3: MODE A — CACHE MODE (pipeline_cache.json)
# ─────────────────────────────────────────────────────────

def push_from_cache(models, uid, blog_id, no_confirm=False, publish_all=False):
    """
    Read pipeline_cache.json (written by auto_pipeline.py) and push to Odoo.
    Shows a preview for each post and asks: Publish / Draft / Discard.
    """
    if not os.path.exists(CACHE_FILE):
        print(f"\n❌ Cache file '{CACHE_FILE}' not found.")
        print("   Run auto_pipeline.py first to generate it:")
        print("   python auto_pipeline.py --scrape-only")
        sys.exit(1)

    with open(CACHE_FILE) as f:
        enriched = json.load(f)

    print(f"\n[MODE A] Loaded {len(enriched)} items from {CACHE_FILE}")

    existing     = get_existing_titles(models, uid)
    pushable     = [ev for ev in enriched if not ev.get("is_past") and ev.get("url_alive", True)]
    skipped_past = sum(1 for ev in enriched if ev.get("is_past"))
    skipped_dead = sum(1 for ev in enriched if not ev.get("url_alive", True))

    print(f"  Ready to push    : {len(pushable)}")
    print(f"  Skipped (past)   : {skipped_past}")
    print(f"  Skipped (dead)   : {skipped_dead}")

    created_count   = 0
    published_count = 0
    discarded_count = 0
    skipped_dup     = 0

    for i, ev in enumerate(pushable, 1):
        title     = ev.get("ai_title", ev.get("original_title", "Untitled"))
        title_key = title.strip().lower()

        print(f"\n  [{i}/{len(pushable)}]", end=" ")

        if title_key in existing:
            print(f"⏭️  DUPLICATE — skipping: {title[:55]}")
            skipped_dup += 1
            continue

        # Build content HTML
        source_url   = ev.get("url", "")
        blog_draft   = ev.get("blog_draft", "")
        content_html = (
            f"<p>{blog_draft}</p>"
            + (f'<p><a href="{source_url}">Read more / Register →</a></p>' if source_url else "")
        )

        # Extra info for preview
        preview_meta = (
            f"Category  : {ev.get('category', 'N/A')}\n"
            f"  Date      : {ev.get('event_date', 'TBD')}\n"
            f"  Source    : {ev.get('source', '')}\n"
            f"  CPD       : {ev.get('cpd_info', 'Not specified')}\n"
            f"  URL       : {source_url}\n\n"
            f"  {blog_draft}"
        )

        choice = ask_user(title, preview_meta, no_confirm=no_confirm, publish_all=publish_all)

        if choice == "d":
            print("  ❌ Discarded.")
            discarded_count += 1
            continue

        post_id = create_draft(models, uid, blog_id, title, content_html, ev.get("event_date"))
        if not post_id:
            continue

        existing[title_key] = {"id": post_id, "website_published": False}
        created_count += 1

        if choice == "p":
            if publish_post(models, uid, post_id):
                print(f"  ✅ Published live! (ID: {post_id})")
                published_count += 1
            else:
                print(f"  📄 Saved as draft (publish failed). (ID: {post_id})")
        else:
            print(f"  📄 Saved as draft. (ID: {post_id})")
            print(f"     → {ODOO_URL}/odoo/website")

        time.sleep(1)

    _print_summary(created_count, published_count, discarded_count, skipped_dup, skipped_past, skipped_dead)


# ─────────────────────────────────────────────────────────
# SECTION 4: MODE B — CSV MODE (Events.csv + News.html)
# ─────────────────────────────────────────────────────────

def read_csv(filepath):
    """Read Events.csv exported from Google Sheet."""
    if not os.path.exists(filepath):
        print(f"\n⚠️  CSV file '{filepath}' not found — skipping blog import.")
        return []

    posts = []
    with open(filepath, "r", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        for row in reader:
            name     = row.get("name", "").strip()
            content  = row.get("content", "").strip()
            postdate = row.get("post_date", "").strip()
            if name and content:
                posts.append({"name": name, "content": content, "post_date": postdate})

    print(f"  Loaded {len(posts)} posts from {filepath}")
    return posts


def push_from_csv(models, uid, blog_id, no_confirm=False, publish_all=False,
                  do_newsletter=True, do_blog=True, do_cleanup=False):
    """
    Read Events.csv and push blog posts to Odoo.
    Optionally update the newsletter page from News.html.
    """
    existing       = get_existing_titles(models, uid)
    created_count  = 0
    published_count = 0
    discarded_count = 0
    skipped_dup    = 0

    # ── Blog Posts ──
    if do_blog:
        csv_posts = read_csv(CSV_FILE)

        if not csv_posts:
            print("  No CSV posts to push.")
        else:
            print(f"\n[MODE B] Pushing {len(csv_posts)} posts from CSV...\n")

            for i, post in enumerate(csv_posts, 1):
                title     = post["name"]
                title_key = title.strip().lower()

                print(f"  [{i}/{len(csv_posts)}]", end=" ")

                if title_key in existing:
                    print(f"⏭️  DUPLICATE — skipping: {title[:55]}")
                    skipped_dup += 1
                    continue

                choice = ask_user(title, post["content"], no_confirm=no_confirm, publish_all=publish_all)

                if choice == "d":
                    print("  ❌ Discarded.")
                    discarded_count += 1
                    continue

                post_id = create_draft(
                    models, uid, blog_id,
                    title, post["content"], post.get("post_date")
                )
                if not post_id:
                    continue

                existing[title_key] = {"id": post_id, "website_published": False}
                created_count += 1

                if choice == "p":
                    if publish_post(models, uid, post_id):
                        print(f"  ✅ Published live! (ID: {post_id})")
                        published_count += 1
                    else:
                        print(f"  📄 Saved as draft (publish failed). (ID: {post_id})")
                else:
                    print(f"  📄 Saved as draft. (ID: {post_id})")
                    print(f"     → {ODOO_URL}/odoo/website")

                time.sleep(1)

        # Cleanup past events
        if do_cleanup and csv_posts:
            _cleanup_past_events(models, uid, csv_posts, existing)

    # ── Newsletter ──
    if do_newsletter:
        _update_newsletter(models, uid)

    _print_summary(created_count, published_count, discarded_count, skipped_dup)


def _cleanup_past_events(models, uid, csv_posts, existing_posts):
    """Unpublish Odoo posts that are no longer in the CSV (past events)."""
    print(f"\n[CLEANUP] Checking for past events to unpublish...")
    csv_titles  = {p["name"].strip().lower() for p in csv_posts}
    unpublished = 0

    for title_key, post_data in existing_posts.items():
        if post_data.get("website_published") and title_key not in csv_titles:
            try:
                models.execute_kw(
                    ODOO_DB, uid, ODOO_PASSWORD,
                    "blog.post", "write",
                    [[post_data["id"]], {"website_published": False}]
                )
                print(f"  📅 Unpublished (past): {post_data.get('name', title_key)[:55]}")
                unpublished += 1
            except Exception as e:
                print(f"  ❌ Failed to unpublish: {e}")

    if unpublished == 0:
        print("  No past events to clean up.")
    else:
        print(f"  → {unpublished} post(s) unpublished")


def _update_newsletter(models, uid):
    """Update the Odoo newsletter page with HTML from News.html."""
    print(f"\n[NEWSLETTER] Updating newsletter page...")

    if not os.path.exists(NEWSLETTER_FILE):
        print(f"  ⚠️  '{NEWSLETTER_FILE}' not found.")
        print(f"  Download it from Google Sheet: SPAN-EA AI → Step 4 → Download Newsletter HTML")
        return False

    with open(NEWSLETTER_FILE, "r", encoding="utf-8") as f:
        newsletter_html = f.read().strip()

    if not newsletter_html:
        print("  ⚠️  Newsletter HTML file is empty — skipping.")
        return False

    pages = models.execute_kw(
        ODOO_DB, uid, ODOO_PASSWORD,
        "website.page", "search_read",
        [[["url", "like", "newsletter"]]],
        {"fields": ["id", "name", "url", "view_id"], "limit": 5}
    )

    if not pages:
        print("  ⚠️  No newsletter page found in Odoo.")
        print("  Create a page at /newsletter in Odoo Website first.")
        return False

    page    = pages[0]
    view_id = page["view_id"][0] if isinstance(page["view_id"], list) else page["view_id"]
    print(f"  Found page: '{page['name']}' at {page['url']}")

    new_arch = (
        '<t t-name="website.newsletter_page">'
        '<t t-call="website.layout">'
        '<div id="wrap" class="oe_structure oe_empty">'
        '<section class="s_text_block pt32 pb32">'
        '<div class="container">'
        + newsletter_html +
        '</div></section></div></t></t>'
    )

    try:
        models.execute_kw(
            ODOO_DB, uid, ODOO_PASSWORD,
            "ir.ui.view", "write",
            [[view_id], {"arch_db": new_arch}]
        )
        print("  ✅ Newsletter page updated!")
        return True
    except Exception as e:
        print(f"  ❌ Could not update newsletter: {e}")
        print("  Fallback: paste News.html content manually into Odoo.")
        return False


# ─────────────────────────────────────────────────────────
# SECTION 5: SUMMARY PRINTER
# ─────────────────────────────────────────────────────────

def _print_summary(created, published, discarded, skipped_dup,
                   skipped_past=0, skipped_dead=0):
    print(f"\n{'=' * 60}")
    print(f"  PUSH COMPLETE")
    print(f"{'=' * 60}")
    print(f"  Posts created    : {created}")
    print(f"  Published live   : {published}")
    print(f"  Saved as draft   : {created - published}")
    print(f"  Discarded        : {discarded}")
    print(f"  Duplicates skip  : {skipped_dup}")
    if skipped_past:
        print(f"  Past events skip : {skipped_past}")
    if skipped_dead:
        print(f"  Dead links skip  : {skipped_dead}")
    print(f"\n  → Review drafts: {ODOO_URL}/odoo/website")
    print(f"{'=' * 60}\n")


# ─────────────────────────────────────────────────────────
# SECTION 6: MAIN
# ─────────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(
        description="SPAN-EA → Odoo Push Script (Cache or CSV mode)"
    )

    # Mode selection
    mode_group = parser.add_mutually_exclusive_group()
    mode_group.add_argument("--cache", action="store_true",
                            help="Force Mode A: read from pipeline_cache.json")
    mode_group.add_argument("--csv",   action="store_true",
                            help="Force Mode B: read from Events.csv + News.html")

    # Behaviour flags
    parser.add_argument("--no-confirm",   action="store_true",
                        help="Save all posts as drafts without asking")
    parser.add_argument("--publish-all",  action="store_true",
                        help="Publish all posts live without asking")

    # Mode B only flags
    parser.add_argument("--cleanup",          action="store_true",
                        help="[CSV mode] Unpublish posts no longer in CSV (past events)")
    parser.add_argument("--blog-only",        action="store_true",
                        help="[CSV mode] Only push blog posts, skip newsletter")
    parser.add_argument("--newsletter-only",  action="store_true",
                        help="[CSV mode] Only update newsletter, skip blog posts")

    args = parser.parse_args()

    print("=" * 60)
    print("  SPAN-EA → ODOO PUSH SCRIPT  v2.0")
    print(f"  {datetime.now().strftime('%B %d, %Y  %H:%M')}")
    print("=" * 60)

    # Connect
    models, uid = authenticate()
    blog_id     = get_or_create_blog(models, uid)

    # Auto-detect mode if neither --cache nor --csv specified
    if not args.cache and not args.csv:
        if os.path.exists(CACHE_FILE):
            print(f"\n  Auto-detected: using {CACHE_FILE} (Mode A)")
            args.cache = True
        elif os.path.exists(CSV_FILE):
            print(f"\n  Auto-detected: using {CSV_FILE} (Mode B)")
            args.csv = True
        else:
            print(f"\n❌ No data source found!")
            print(f"   Run auto_pipeline.py first  OR  export Events.csv from Google Sheet")
            sys.exit(1)

    # Run selected mode
    if args.cache:
        push_from_cache(
            models, uid, blog_id,
            no_confirm  = args.no_confirm,
            publish_all = args.publish_all,
        )
    else:
        push_from_csv(
            models, uid, blog_id,
            no_confirm      = args.no_confirm,
            publish_all     = args.publish_all,
            do_newsletter   = not args.blog_only,
            do_blog         = not args.newsletter_only,
            do_cleanup      = args.cleanup,
        )


if __name__ == "__main__":
    main()