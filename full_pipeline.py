"""
SPAN-EA Full Pipeline Orchestrator — Version 2.0
==================================================

FEATURES:
  FEATURE 1  — Google Apps Script Runner
  FEATURE 1B — Auto-Fetch Exports from Google Sheets
  FEATURE 2  — Odoo Expiry Cleanup (ARCHIVE MODE — never deletes)
  FEATURE 3  — API mode via pipeline_api.py (two-button Odoo integration)

Usage (CLI):
    python full_pipeline.py                  # Run everything interactively
    python full_pipeline.py --skip-gas       # Skip Apps Script
    python full_pipeline.py --no-confirm     # Auto-save all posts as drafts
    python full_pipeline.py --publish-all    # Auto-publish everything
    python full_pipeline.py --dry-run        # Preview only, no changes
    python full_pipeline.py --blog-only      # Blog posts only, skip newsletter

Required .env:
    ODOO_URL, ODOO_DB, ODOO_USER, ODOO_PASSWORD
    GAS_SCRIPT_ID, SPREADSHEET_ID
    TOKEN_PICKLE_B64=<base64 token for Railway>
"""

import os
import sys
import json
import time
import argparse
import xmlrpc.client
from datetime import datetime


# ─────────────────────────────────────────────────────────
# SECTION 0: CONFIG
# ─────────────────────────────────────────────────────────

if os.path.exists(".env"):
    with open(".env") as f:
        for line in f:
            line = line.strip()
            if "=" in line and not line.startswith("#"):
                key, value = line.split("=", 1)
                os.environ[key.strip()] = value.strip()

ODOO_URL        = os.getenv("ODOO_URL", "").rstrip("/")
ODOO_DB         = os.getenv("ODOO_DB", "")
ODOO_USER       = os.getenv("ODOO_USER", "")
ODOO_PASSWORD   = os.getenv("ODOO_PASSWORD", "")
GAS_SCRIPT_ID   = os.getenv("GAS_SCRIPT_ID", "")
SPREADSHEET_ID  = os.getenv("SPREADSHEET_ID", "")
CACHE_FILE      = "pipeline_cache.json"
CSV_FILE        = os.getenv("CSV_FILE", "Events.csv")
NEWSLETTER_FILE = os.getenv("NEWSLETTER_FILE", "News.html")


# ─────────────────────────────────────────────────────────
# SECTION 0B: SOURCE BUTTON HELPER
# ─────────────────────────────────────────────────────────

def build_post_content(blog_draft, source_url=""):
    """
    Build full HTML for a blog post.
    Appends a styled blue 'View Original Source' button when a URL is provided.
    """
    content = f"<p>{blog_draft}</p>"
    if source_url and source_url.strip():
        content += (
            '<p style="margin-top:24px;">'
            f'<a href="{source_url.strip()}" target="_blank" rel="noopener noreferrer" '
            'style="display:inline-block;padding:10px 24px;background-color:#2e6da4;'
            'color:#ffffff;text-decoration:none;border-radius:6px;font-weight:600;'
            'font-size:14px;box-shadow:0 2px 6px rgba(0,0,0,0.15);">'
            '&#128279; View Original Source &rarr;'
            '</a></p>'
        )
    return content


# ─────────────────────────────────────────────────────────
# SECTION 0C: GOOGLE CREDENTIALS
# ─────────────────────────────────────────────────────────

def get_google_creds():
    try:
        import pickle
        from google.auth.transport.requests import Request
        creds     = None
        token_b64 = os.getenv("TOKEN_PICKLE_B64", "")
        if token_b64:
            import base64
            creds = pickle.loads(base64.b64decode(token_b64))
        elif os.path.exists("token.pickle"):
            with open("token.pickle", "rb") as f:
                creds = pickle.load(f)
        if creds and creds.expired and creds.refresh_token:
            creds.refresh(Request())
            if not token_b64 and os.path.exists("token.pickle"):
                with open("token.pickle", "wb") as f:
                    pickle.dump(creds, f)
        return creds
    except Exception as e:
        print(f"  ⚠️  Could not load credentials: {e}")
        return None


# ─────────────────────────────────────────────────────────
# SECTION 1: RUN ALL Code.gs FUNCTIONS
# ─────────────────────────────────────────────────────────

GAS_FUNCTIONS_SEQUENCE = [
    ("processDataRowByRow", "Step 2: AI Process Pending Data"),
    ("flagUpcomingEvents",  "Step 3: Flag Upcoming Events"),
    ("generateWeeklyPulse", "Step 4: Generate Newsletter HTML"),
    ("exportCSVForOdoo",    "Step 5: Export Events CSV"),
]


def run_gas_function(service, script_id, function_name, dry_run=False):
    if dry_run:
        print(f"    [DRY-RUN] Would call: {function_name}()")
        return True
    try:
        response = service.scripts().run(
            scriptId=script_id,
            body={"function": function_name, "devMode": True}
        ).execute()
        if "error" in response:
            error     = response["error"]["details"][0] if response["error"].get("details") else response["error"]
            error_msg = error.get("errorMessage", str(error)) if isinstance(error, dict) else str(error)
            print(f"    ❌ Script error: {error_msg}")
            return False
        print(f"    ✅ {function_name}() completed successfully")
        return True
    except Exception as e:
        err_str = str(e)
        if "Script function not found" in err_str:
            print(f"    ⚠️  Function '{function_name}' not found — skipping")
            return True
        if any(x in err_str.lower() for x in ["no window", "ui", "dialog", "htmlservice"]):
            print(f"    ℹ️  {function_name}() ran (UI suppressed in headless mode)")
            return True
        print(f"    ❌ API error: {e}")
        return False


def run_all_gas_functions(dry_run=False):
    print("\n" + "=" * 60)
    print("  FEATURE 1: Running Code.gs Functions via Apps Script API")
    print("=" * 60)

    if not GAS_SCRIPT_ID:
        print("\n  ⚠️  GAS_SCRIPT_ID not set in .env — skipping.")
        return False

    try:
        from googleapiclient.discovery import build
    except ImportError:
        print("\n  ❌ Google API libraries not installed.")
        return False

    creds = get_google_creds()
    if not creds:
        try:
            from google_auth_oauthlib.flow import InstalledAppFlow
            import pickle
            SCOPES = [
                "https://www.googleapis.com/auth/script.projects",
                "https://www.googleapis.com/auth/script.external_request",
                "https://www.googleapis.com/auth/spreadsheets",
                "https://www.googleapis.com/auth/drive",
            ]
            OAUTH_SECRET = os.getenv("OAUTH_CLIENT_SECRET_JSON", "client_secret.json")
            if not os.path.exists(OAUTH_SECRET):
                print(f"\n  ❌ OAuth client secret not found: '{OAUTH_SECRET}'")
                return False
            print("\n  🌐 Opening browser for Google login (one-time only)...")
            flow  = InstalledAppFlow.from_client_secrets_file(OAUTH_SECRET, SCOPES)
            creds = flow.run_local_server(port=0, open_browser=True)
            with open("token.pickle", "wb") as token:
                pickle.dump(creds, token)
            print("  ✅ Login successful — token saved to token.pickle")
        except Exception as e:
            print(f"  ❌ Authentication failed: {e}")
            return False

    try:
        service = build("script", "v1", credentials=creds, cache_discovery=False)
        print(f"  ✅ Authenticated as your Google account")
        print(f"  Script ID: {GAS_SCRIPT_ID[:20]}...")
    except Exception as e:
        print(f"  ❌ Failed to build Apps Script service: {e}")
        return False

    all_ok = True
    for func_name, step_label in GAS_FUNCTIONS_SEQUENCE:
        print(f"\n  ▶  {step_label} ({func_name})")
        ok = run_gas_function(service, GAS_SCRIPT_ID, func_name, dry_run=dry_run)
        if not ok:
            all_ok = False
            print(f"  ⚠️  {func_name} had issues — continuing")
        if not dry_run:
            time.sleep(3)

    print("\n  ✅ All Code.gs functions completed!" if all_ok else "\n  ⚠️  Some steps had issues — continuing.")
    if not dry_run:
        print("  ⏳ Waiting 5s for spreadsheet to finish writing...")
        time.sleep(5)
    return all_ok


# ─────────────────────────────────────────────────────────
# SECTION 1B: AUTO-FETCH EXPORTS FROM GOOGLE SHEETS
# ─────────────────────────────────────────────────────────

def fetch_exports_from_sheets(dry_run=False):
    print("\n  📥 Auto-fetching exports from Google Sheets...")
    if not SPREADSHEET_ID:
        print("  ⚠️  SPREADSHEET_ID not set in .env — cannot auto-fetch.")
        return False
    try:
        from googleapiclient.discovery import build
    except ImportError:
        print("  ❌ Google API libraries not installed.")
        return False
    creds = get_google_creds()
    if not creds:
        print("  ⚠️  No valid credentials — skipping auto-fetch.")
        return False
    try:
        sheets_svc = build("sheets", "v4", credentials=creds, cache_discovery=False)
    except Exception as e:
        print(f"  ❌ Failed to build Sheets service: {e}")
        return False

    fetched_any = False

    # Events Export → Events.csv
    try:
        result = sheets_svc.spreadsheets().values().get(
            spreadsheetId=SPREADSHEET_ID, range="Events Export!A:D"
        ).execute()
        rows = result.get("values", [])
        if len(rows) < 2:
            print("  ⚠️  'Events Export' tab is empty.")
        else:
            import csv as csv_module, io
            output = io.StringIO()
            writer = csv_module.writer(output, quoting=csv_module.QUOTE_ALL)
            for row in rows:
                while len(row) < 4:
                    row.append("")
                writer.writerow(row[:4])
            if not dry_run:
                with open(CSV_FILE, "w", encoding="utf-8", newline="") as f:
                    f.write(output.getvalue())
                print(f"  ✅ Events.csv written  ({len(rows) - 1} posts)")
            else:
                print(f"  [DRY-RUN] Would write Events.csv ({len(rows) - 1} posts)")
            fetched_any = True
    except Exception as e:
        print(f"  ❌ Failed to fetch 'Events Export': {e}")

    # Newsletter Draft → News.html
    try:
        result = sheets_svc.spreadsheets().values().get(
            spreadsheetId=SPREADSHEET_ID, range="Newsletter Draft!A1"
        ).execute()
        rows         = result.get("values", [])
        html_content = rows[0][0] if rows and rows[0] else ""
        if not html_content:
            print("  ⚠️  'Newsletter Draft' tab is empty.")
        else:
            if not dry_run:
                with open(NEWSLETTER_FILE, "w", encoding="utf-8") as f:
                    f.write(html_content)
                print(f"  ✅ News.html written   ({len(html_content):,} chars)")
            else:
                print(f"  [DRY-RUN] Would write News.html ({len(html_content):,} chars)")
            fetched_any = True
    except Exception as e:
        print(f"  ❌ Failed to fetch 'Newsletter Draft': {e}")

    return fetched_any


# ─────────────────────────────────────────────────────────
# SECTION 2: ODOO HELPERS
# ─────────────────────────────────────────────────────────

def odoo_connect():
    if not ODOO_URL or not ODOO_USER or not ODOO_PASSWORD:
        raise RuntimeError("Missing Odoo credentials in .env")
    print(f"\n[ODOO] Connecting to {ODOO_URL}...")
    common = xmlrpc.client.ServerProxy(f"{ODOO_URL}/xmlrpc/2/common")
    try:
        v = common.version()
        print(f"  Odoo version : {v.get('server_version', 'unknown')}")
    except Exception as e:
        raise RuntimeError(f"Cannot connect to Odoo: {e}")
    uid = common.authenticate(ODOO_DB, ODOO_USER, ODOO_PASSWORD, {})
    if not uid:
        raise RuntimeError("Odoo authentication failed — check credentials")
    print(f"  ✅ Authenticated (UID: {uid})")
    models = xmlrpc.client.ServerProxy(f"{ODOO_URL}/xmlrpc/2/object")
    return models, uid


def smart_parse_date(raw):
    import re
    if not raw:
        return None
    s = str(raw).strip()
    s = re.sub(r"(\d+)(st|nd|rd|th)", r"\1", s)
    s = re.sub(r"(?:Monday|Tuesday|Wednesday|Thursday|Friday|Saturday|Sunday|Mon|Tue|Wed|Thu|Fri|Sat|Sun),?\s*",
               "", s, flags=re.IGNORECASE)
    for fmt in ("%B %d, %Y", "%Y-%m-%d %H:%M:%S", "%Y-%m-%d"):
        try:
            return datetime.strptime(s.strip(), fmt)
        except ValueError:
            pass
    try:
        return datetime.strptime(s + f", {datetime.now().year}", "%B %d, %Y")
    except ValueError:
        pass
    return None


# ─────────────────────────────────────────────────────────
# SECTION 3: ODOO EXPIRY CLEANUP — ARCHIVE MODE
# ─────────────────────────────────────────────────────────

def get_or_create_archive_blog(models, uid):
    blogs = models.execute_kw(
        ODOO_DB, uid, ODOO_PASSWORD,
        "blog.blog", "search_read",
        [[("name", "=", "Archive")]], {"fields": ["id", "name"], "limit": 1}
    )
    if blogs:
        return blogs[0]["id"]
    archive_id = models.execute_kw(
        ODOO_DB, uid, ODOO_PASSWORD,
        "blog.blog", "create", [{"name": "Archive"}]
    )
    print(f"  📁 Created 'Archive' blog (ID: {archive_id})")
    return archive_id


def cleanup_expired_odoo_content(models, uid, dry_run=False, auto_confirm=False):
    print("\n" + "=" * 60)
    print("  FEATURE 2: Odoo Expiry Cleanup — Archive Mode")
    print("=" * 60)

    today   = datetime.now().replace(hour=0, minute=0, second=0, microsecond=0)
    summary = {
        "expired_posts_found":    0,
        "expired_posts_archived": 0,
        "newsletter_cleared":     False,
        "errors":                 [],
    }

    print(f"\n  Pass A: Checking for expired blog posts (before {today.strftime('%Y-%m-%d')})...")
    try:
        all_posts = models.execute_kw(
            ODOO_DB, uid, ODOO_PASSWORD,
            "blog.post", "search_read",
            [[("website_published", "=", True)]],
            {"fields": ["id", "name", "published_date", "website_published"], "limit": 500}
        )
        expired = [p for p in all_posts
                   if p.get("published_date") and smart_parse_date(p["published_date"]) and
                   smart_parse_date(p["published_date"]) < today]

        summary["expired_posts_found"] = len(expired)

        if not expired:
            print("  ✅ No expired published posts found.")
        else:
            print(f"  Found {len(expired)} expired post(s):")
            for post in expired:
                print(f"    • [{post['id']}] {post['name'][:60]}")

            if dry_run:
                print(f"  [DRY-RUN] Would archive {len(expired)} post(s) → Archive blog.")
            else:
                do_archive = True
                if not auto_confirm:
                    print(f"\n  ⚠️  These will be MOVED to Archive blog (not deleted).")
                    choice     = input("  Archive them all? [Y/n]: ").strip().lower()
                    do_archive = choice in ("y", "yes", "")
                if do_archive:
                    archive_blog_id = get_or_create_archive_blog(models, uid)
                    for post in expired:
                        try:
                            models.execute_kw(
                                ODOO_DB, uid, ODOO_PASSWORD,
                                "blog.post", "write",
                                [[post["id"]], {"website_published": False, "blog_id": archive_blog_id}]
                            )
                            print(f"    📁 Archived: {post['name'][:60]}")
                            summary["expired_posts_archived"] += 1
                        except Exception as e:
                            err = f"Failed to archive post {post['id']}: {e}"
                            print(f"    ❌ {err}")
                            summary["errors"].append(err)
                else:
                    print("  ⏭️  Skipped.")
    except Exception as e:
        summary["errors"].append(f"Error fetching posts: {e}")
        print(f"  ❌ {e}")

    print(f"\n  Pass B: Checking newsletter page...")
    try:
        pages = models.execute_kw(
            ODOO_DB, uid, ODOO_PASSWORD,
            "website.page", "search_read",
            [[("url", "like", "newsletter")]],
            {"fields": ["id", "name", "url", "view_id"], "limit": 5}
        )
        if not pages:
            print("  ℹ️  No newsletter page found.")
        else:
            page    = pages[0]
            view_id = page["view_id"][0] if isinstance(page["view_id"], list) else page["view_id"]
            print(f"  Found: '{page['name']}' at {page['url']}")
            views = models.execute_kw(
                ODOO_DB, uid, ODOO_PASSWORD,
                "ir.ui.view", "read", [[view_id]], {"fields": ["arch_db"]}
            )
            if views and views[0].get("arch_db"):
                has_content = any(x in views[0]["arch_db"] for x in
                                  ["SPAN-EA NEWSLETTER", "s_title", "s_features_grid"])
                if has_content:
                    if dry_run or auto_confirm:
                        summary["newsletter_cleared"] = True
                        print("  ✅ Newsletter page will be replaced during push.")
                    else:
                        choice = input("  Replace newsletter with new content? [Y/n]: ").strip().lower()
                        if choice in ("y", "yes", ""):
                            summary["newsletter_cleared"] = True
                            print("  ✅ Will be replaced during push.")
                        else:
                            print("  ⏭️  Keeping existing newsletter.")
                else:
                    summary["newsletter_cleared"] = True
                    print("  ✅ Ready for fresh content.")
    except Exception as e:
        summary["errors"].append(f"Newsletter check error: {e}")
        print(f"  ❌ {e}")

    print(f"\n  Summary: {summary['expired_posts_archived']} archived | Newsletter refresh: {'Yes' if summary['newsletter_cleared'] else 'No'}")
    return summary


# ─────────────────────────────────────────────────────────
# SECTION 4: PUSH LOGIC
# ─────────────────────────────────────────────────────────

def get_or_create_blog(models, uid):
    blogs = models.execute_kw(
        ODOO_DB, uid, ODOO_PASSWORD,
        "blog.blog", "search_read",
        [[("name", "!=", "Archive")]], {"fields": ["id", "name"], "limit": 1}
    )
    if blogs:
        print(f"  Blog: '{blogs[0]['name']}' (ID: {blogs[0]['id']})")
        return blogs[0]["id"]
    blog_id = models.execute_kw(
        ODOO_DB, uid, ODOO_PASSWORD,
        "blog.blog", "create", [{"name": "Our blog"}]
    )
    print(f"  Created new blog (ID: {blog_id})")
    return blog_id


def get_existing_titles(models, uid):
    posts = models.execute_kw(
        ODOO_DB, uid, ODOO_PASSWORD,
        "blog.post", "search_read",
        [[]], {"fields": ["id", "name", "website_published"], "limit": 500}
    )
    return {p["name"].strip().lower(): p for p in posts}


def create_draft(models, uid, blog_id, title, content_html, event_date_str=None):
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
        return models.execute_kw(ODOO_DB, uid, ODOO_PASSWORD, "blog.post", "create", [post_data])
    except Exception:
        post_data.pop("post_date", None)
        try:
            return models.execute_kw(ODOO_DB, uid, ODOO_PASSWORD, "blog.post", "create", [post_data])
        except Exception as e2:
            print(f"    ❌ Failed: {e2}")
            return None


def publish_post(models, uid, post_id):
    try:
        models.execute_kw(ODOO_DB, uid, ODOO_PASSWORD, "blog.post", "write",
                          [[post_id], {"website_published": True}])
        return True
    except Exception as e:
        print(f"    ❌ Publish failed: {e}")
        return False


def push_from_csv(models, uid, blog_id, no_confirm=False, publish_all=False,
                  do_newsletter=True, dry_run=False, newsletter_cleared=False,
                  auto_confirm=False):
    import csv, re as _re
    posts = []
    if os.path.exists(CSV_FILE):
        with open(CSV_FILE, "r", encoding="utf-8") as f:
            for row in csv.DictReader(f):
                name    = row.get("name", "").strip()
                content = row.get("content", "").strip()
                pd      = row.get("post_date", "").strip()
                # Extract source URL embedded by Code.gs
                source_url = ""
                m = _re.search(r'href="([^"]+)"', content)
                if m:
                    source_url = m.group(1)
                # Extract plain blog text
                blog_text = content
                p_match = _re.search(r'<p>(.*?)</p>', content, _re.DOTALL)
                if p_match:
                    blog_text = p_match.group(1)
                if name and content:
                    posts.append({
                        "name":       name,
                        "blog_text":  blog_text,
                        "post_date":  pd,
                        "source_url": source_url,
                    })
        print(f"\n[PUSH] Loaded {len(posts)} posts from {CSV_FILE}")
    else:
        print(f"\n⚠️  '{CSV_FILE}' not found — skipping blog post push.")

    existing = get_existing_titles(models, uid)
    created = published = discarded = skipped = 0

    for i, post in enumerate(posts, 1):
        title_key = post["name"].strip().lower()
        if title_key in existing:
            print(f"  [{i}/{len(posts)}] ⏭️  Duplicate: {post['name'][:55]}")
            skipped += 1
            continue

        print(f"\n  [{i}/{len(posts)}] {post['name'][:65]}")
        if dry_run:
            created += 1
            continue

        # Build content with styled source button
        content_html = build_post_content(post["blog_text"], post.get("source_url", ""))

        choice = "s" if (auto_confirm or no_confirm) else _ask(no_confirm, publish_all)
        if choice == "d":
            discarded += 1
            continue

        post_id = create_draft(models, uid, blog_id, post["name"], content_html, post.get("post_date"))
        if not post_id:
            continue
        existing[title_key] = {"id": post_id}
        created += 1
        if choice == "p":
            if publish_post(models, uid, post_id):
                print(f"  ✅ Published! (ID: {post_id})")
                published += 1
        else:
            print(f"  📄 Saved as draft. (ID: {post_id})")
        time.sleep(1)

    _print_summary(created, published, discarded, skipped)
    if do_newsletter and newsletter_cleared:
        _update_newsletter(models, uid, dry_run)
    return created


def push_from_cache(models, uid, blog_id, no_confirm=False, publish_all=False, dry_run=False):
    if not os.path.exists(CACHE_FILE):
        return None
    with open(CACHE_FILE) as f:
        enriched = json.load(f)
    existing = get_existing_titles(models, uid)
    pushable = [ev for ev in enriched if not ev.get("is_past") and ev.get("url_alive", True)]
    print(f"\n[PUSH] {len(pushable)} posts from cache")
    created = published = discarded = skipped = 0
    for i, ev in enumerate(pushable, 1):
        title = ev.get("ai_title", ev.get("original_title", "Untitled"))
        if title.strip().lower() in existing:
            skipped += 1
            continue
        source_url   = ev.get("url", "")
        blog_draft   = ev.get("blog_draft", "")
        content_html = build_post_content(blog_draft, source_url)
        if dry_run:
            created += 1
            continue
        choice = _ask(no_confirm, publish_all)
        if choice == "d":
            discarded += 1
            continue
        post_id = create_draft(models, uid, blog_id, title, content_html, ev.get("event_date"))
        if post_id:
            existing[title.strip().lower()] = {"id": post_id}
            created += 1
            if choice == "p" and publish_post(models, uid, post_id):
                published += 1
        time.sleep(1)
    _print_summary(created, published, discarded, skipped)
    return created


def _update_newsletter(models, uid, dry_run=False):
    print(f"\n[NEWSLETTER] Updating newsletter page...")
    if not os.path.exists(NEWSLETTER_FILE):
        print(f"  ⚠️  '{NEWSLETTER_FILE}' not found.")
        return False
    with open(NEWSLETTER_FILE, "r", encoding="utf-8") as f:
        html = f.read().strip()
    if not html:
        print("  ⚠️  Newsletter file is empty.")
        return False
    pages = models.execute_kw(
        ODOO_DB, uid, ODOO_PASSWORD,
        "website.page", "search_read",
        [[("url", "like", "newsletter")]],
        {"fields": ["id", "name", "url", "view_id"], "limit": 1}
    )
    if not pages:
        print("  ⚠️  No newsletter page found in Odoo.")
        return False
    page    = pages[0]
    view_id = page["view_id"][0] if isinstance(page["view_id"], list) else page["view_id"]
    new_arch = (
        '<t t-name="website.newsletter_page"><t t-call="website.layout">'
        '<div id="wrap" class="oe_structure oe_empty">'
        '<section class="s_text_block pt32 pb32"><div class="container">'
        + html + '</div></section></div></t></t>'
    )
    if dry_run:
        print(f"  [DRY-RUN] Would update '{page['name']}' at {page['url']}")
        return True
    try:
        models.execute_kw(ODOO_DB, uid, ODOO_PASSWORD, "ir.ui.view", "write",
                          [[view_id], {"arch_db": new_arch}])
        print(f"  ✅ Newsletter page updated: {page['url']}")
        return True
    except Exception as e:
        print(f"  ❌ Failed to update newsletter: {e}")
        return False


def _ask(no_confirm, publish_all):
    if publish_all: return "p"
    if no_confirm:  return "s"
    print("\n  [P] Publish now  |  [S] Save as draft  |  [D] Discard")
    return input("  Your choice: ").strip().lower()


def _print_summary(created, published, discarded, skipped):
    print(f"\n{'═' * 60}")
    print(f"  Posts created : {created}  |  Published: {published}  |  Drafts: {created - published}  |  Skipped: {skipped}")
    print(f"  → Review: {ODOO_URL}/odoo/website")
    print(f"{'═' * 60}\n")


# ─────────────────────────────────────────────────────────
# SECTION 5: MAIN (CLI mode)
# ─────────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(description="SPAN-EA Full Pipeline v2.0")
    parser.add_argument("--skip-gas",     action="store_true")
    parser.add_argument("--skip-cleanup", action="store_true")
    parser.add_argument("--no-confirm",   action="store_true")
    parser.add_argument("--publish-all",  action="store_true")
    parser.add_argument("--dry-run",      action="store_true")
    parser.add_argument("--blog-only",    action="store_true")
    args = parser.parse_args()

    print("=" * 60)
    print("  SPAN-EA FULL PIPELINE  v2.0")
    print(f"  {datetime.now().strftime('%B %d, %Y  %H:%M')}")
    if args.dry_run:
        print("  *** DRY-RUN MODE ***")
    print("=" * 60)

    gas_ok = False
    if not args.skip_gas:
        gas_ok = run_all_gas_functions(dry_run=args.dry_run)
        if gas_ok:
            fetch_exports_from_sheets(dry_run=args.dry_run)

    try:
        models, uid = odoo_connect()
    except RuntimeError as e:
        print(f"\n❌ {e}")
        sys.exit(1)

    blog_id = get_or_create_blog(models, uid)

    if args.skip_cleanup:
        cleanup_summary = {"newsletter_cleared": True, "errors": [], "expired_posts_archived": 0}
    else:
        cleanup_summary = cleanup_expired_odoo_content(models, uid, dry_run=args.dry_run)

    newsletter_cleared = cleanup_summary.get("newsletter_cleared", False)

    print("\n" + "=" * 60)
    print("  STEP 4: Pushing New Content to Odoo")
    print("=" * 60)

    if os.path.exists(CACHE_FILE):
        result = push_from_cache(models, uid, blog_id,
                                 no_confirm=args.no_confirm,
                                 publish_all=args.publish_all,
                                 dry_run=args.dry_run)
        if result is not None and not args.blog_only and newsletter_cleared:
            _update_newsletter(models, uid, dry_run=args.dry_run)
    elif os.path.exists(CSV_FILE):
        push_from_csv(models, uid, blog_id,
                      no_confirm=args.no_confirm,
                      publish_all=args.publish_all,
                      do_newsletter=not args.blog_only,
                      dry_run=args.dry_run,
                      newsletter_cleared=newsletter_cleared)
    else:
        print(f"\n  ❌ Neither '{CACHE_FILE}' nor '{CSV_FILE}' found.")
        sys.exit(1)

    print("\n" + "=" * 60)
    print("  ✅ FULL PIPELINE COMPLETE")
    print("=" * 60)
    print(f"  Archived  : {cleanup_summary.get('expired_posts_archived', 0)} post(s) → Archive blog")
    print(f"  Newsletter: {'Refreshed' if newsletter_cleared else 'Kept as-is'}")
    print(f"  → {ODOO_URL}/odoo/website")
    print("=" * 60 + "\n")


if __name__ == "__main__":
    main()
