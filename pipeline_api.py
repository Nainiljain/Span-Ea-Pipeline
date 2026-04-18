"""
SPAN-EA Pipeline API Server
============================
Flask API that powers the two-button Odoo integration.

Endpoints:
  GET  /api/health                → Server health check
  POST /api/run-blog              → Start blog pipeline job
  POST /api/run-newsletter        → Start newsletter pipeline job
  GET  /api/job/<job_id>          → Poll job status + live logs
"""

import os
import threading
import uuid
from datetime import datetime
from flask import Flask, jsonify, request
from flask_cors import CORS

if os.path.exists(".env"):
    with open(".env") as f:
        for line in f:
            line = line.strip()
            if "=" in line and not line.startswith("#"):
                key, val = line.split("=", 1)
                os.environ[key.strip()] = val.strip()

app = Flask(__name__)
CORS(app, origins="*")
jobs = {}


def make_job(job_type):
    job_id = str(uuid.uuid4())[:8]
    jobs[job_id] = {
        "id": job_id, "type": job_type, "status": "queued",
        "logs": [], "result": None, "error": None,
        "started_at": datetime.now().isoformat(), "finished_at": None,
    }
    return job_id


def log(job_id, msg):
    ts = datetime.now().strftime("%H:%M:%S")
    line = f"[{ts}] {msg}"
    jobs[job_id]["logs"].append(line)
    print(f"[job:{job_id}] {msg}", flush=True)


def run_blog_job(job_id):
    job = jobs[job_id]
    job["status"] = "running"
    try:
        import full_pipeline as fp

        log(job_id, "🚀 Blog pipeline started")

        # Step 1: Run Code.gs functions
        log(job_id, "▶ Running Google Apps Script functions...")
        gas_ok = fp.run_all_gas_functions(dry_run=False)
        if gas_ok:
            log(job_id, "✅ Code.gs functions complete")
        else:
            log(job_id, "⚠️  GAS had issues — continuing to fetch from Sheets")

        # Step 2: ALWAYS fetch fresh data from Sheet1 directly
        log(job_id, "📥 Fetching fresh data from Google Sheets (Sheet1)...")
        fetch_ok = fp.fetch_exports_from_sheets(dry_run=False)
        if fetch_ok:
            log(job_id, "✅ Events.csv downloaded with AI content + source URLs")
        else:
            log(job_id, "⚠️  Could not fetch from Sheets — using existing files")

        # Step 3: Connect to Odoo
        log(job_id, "🔗 Connecting to Odoo...")
        models, uid = fp.odoo_connect()
        blog_id = fp.get_or_create_blog(models, uid)
        log(job_id, "✅ Odoo authenticated")

        # Step 4: Archive expired posts
        log(job_id, "🗂  Checking for expired posts...")
        cleanup = fp.cleanup_expired_odoo_content(
            models, uid, dry_run=False, auto_confirm=True
        )
        archived = cleanup.get("expired_posts_archived", 0)
        log(job_id, f"📁 Archived {archived} expired post(s) → Archive blog")

        # Step 5: Push new posts as drafts
        log(job_id, "📤 Pushing new blog posts as unpublished drafts...")
        pushed = fp.push_from_csv(
            models, uid, blog_id,
            no_confirm=True, dry_run=False,
            do_newsletter=False, newsletter_cleared=False,
            auto_confirm=True,
        )
        pushed = pushed or 0
        log(job_id, f"✅ Done! {pushed} new post(s) created as drafts")
        log(job_id, f"→ Review at: {fp.ODOO_URL}/odoo/website")

        job["status"] = "complete"
        job["result"] = {
            "gas_ok": gas_ok, "archived": archived,
            "pushed": pushed, "odoo_url": f"{fp.ODOO_URL}/odoo/website",
        }
    except Exception as e:
        import traceback
        log(job_id, f"❌ Error: {str(e)}")
        job["status"] = "error"
        job["error"] = str(e)
        print(traceback.format_exc(), flush=True)
    finally:
        job["finished_at"] = datetime.now().isoformat()


def run_newsletter_job(job_id):
    job = jobs[job_id]
    job["status"] = "running"
    try:
        import full_pipeline as fp

        log(job_id, "🚀 Newsletter pipeline started")

        # Step 1: Run Code.gs functions
        log(job_id, "▶ Running Google Apps Script functions...")
        gas_ok = fp.run_all_gas_functions(dry_run=False)
        if gas_ok:
            log(job_id, "✅ Code.gs functions complete")
        else:
            log(job_id, "⚠️  GAS had issues — continuing to fetch from Sheets")

        # Step 2: ALWAYS fetch fresh data from Sheets
        log(job_id, "📥 Fetching fresh newsletter from Google Sheets...")
        fetch_ok = fp.fetch_exports_from_sheets(dry_run=False)
        if fetch_ok:
            log(job_id, "✅ News.html downloaded from Sheets")
        else:
            log(job_id, "⚠️  Could not fetch — using existing News.html")

        # Step 3: Connect to Odoo
        log(job_id, "🔗 Connecting to Odoo...")
        models, uid = fp.odoo_connect()
        log(job_id, "✅ Odoo authenticated")

        # Step 4: Archive expired posts
        log(job_id, "🗂  Checking for expired posts...")
        cleanup = fp.cleanup_expired_odoo_content(
            models, uid, dry_run=False, auto_confirm=True
        )
        archived = cleanup.get("expired_posts_archived", 0)
        log(job_id, f"📁 Archived {archived} expired post(s) → Archive blog")

        # Step 5: Update newsletter page
        log(job_id, "📰 Updating newsletter page in Odoo...")
        success = fp._update_newsletter(models, uid, dry_run=False)
        if success:
            log(job_id, "✅ Newsletter page updated with fresh content!")
        else:
            log(job_id, "⚠️  Newsletter update had issues")
        log(job_id, f"→ View at: {fp.ODOO_URL}/newsletter")

        job["status"] = "complete"
        job["result"] = {
            "gas_ok": gas_ok, "archived": archived,
            "newsletter_updated": success,
            "newsletter_url": f"{fp.ODOO_URL}/newsletter",
        }
    except Exception as e:
        import traceback
        log(job_id, f"❌ Error: {str(e)}")
        job["status"] = "error"
        job["error"] = str(e)
        print(traceback.format_exc(), flush=True)
    finally:
        job["finished_at"] = datetime.now().isoformat()


@app.route("/api/health", methods=["GET"])
def health():
    return jsonify({
        "status": "ok", "service": "SPAN-EA Pipeline API",
        "time": datetime.now().isoformat(),
    })

@app.route("/api/run-blog", methods=["POST"])
def run_blog():
    job_id = make_job("blog")
    threading.Thread(target=run_blog_job, args=(job_id,), daemon=True).start()
    log(job_id, "Job queued — starting pipeline...")
    return jsonify({"job_id": job_id, "status": "started"})

@app.route("/api/run-newsletter", methods=["POST"])
def run_newsletter():
    job_id = make_job("newsletter")
    threading.Thread(target=run_newsletter_job, args=(job_id,), daemon=True).start()
    log(job_id, "Job queued — starting pipeline...")
    return jsonify({"job_id": job_id, "status": "started"})

@app.route("/api/job/<job_id>", methods=["GET"])
def get_job_status(job_id):
    job = jobs.get(job_id)
    if not job:
        return jsonify({"error": "Job not found"}), 404
    return jsonify(job)

@app.route("/api/jobs", methods=["GET"])
def list_jobs():
    sorted_jobs = sorted(jobs.values(), key=lambda j: j["started_at"], reverse=True)
    return jsonify(sorted_jobs[:20])

if __name__ == "__main__":
    port = int(os.getenv("PORT", 5000))
    print(f"🚀 SPAN-EA Pipeline API starting on port {port}")
    app.run(host="0.0.0.0", port=port, debug=False)
