# 🎬 SPAN-EA Demo Guide: The Complete Flow

**This document demonstrates every step of the system, from scraping data to publishing a blog on the Odoo website.**

---

## 🔵 System Architecture (Overview)

```text
┌─────────────┐    ┌──────────────────┐    ┌──────────────────┐
│   PYTHON    │──→│  GOOGLE SHEETS   │──→│      ODOO        │
│  Scraper    │    │  + Gemini AI     │    │  Website/Blog    │
└─────────────┘    └──────────────────┘    └──────────────────┘

   Step 1              Steps 2-5              Step 6
 Scrape Web      AI Process + Export     Direct Push to Odoo
```

**What we do:** Scrape news/events from TSA, OAA, PEO, OSPE → AI writes blog drafts → Push directly to Odoo Blog and Newsletter via JSON-RPC.

---

## Step 1: Scrape Data (Python)

```bash
python scrape_events.py
```

**Result:** 10-15 raw data items are sent directly to the Google Sheet via Webhook.
- TSA (Toronto Society of Architects) — HTML + RSS
- Google News RSS — OAA, PEO, OSPE articles

---

## Step 2: Human QA Review (Google Sheet)

Open Google Sheet → Look for new rows with Status = **"Pending"**

Use the **QA Dropdown** (Column G) to mark each row:

| QA Dropdown Option | Result |
|--------|---------|
| *(Leave empty)* | Status = Pending (Ready for AI processing) |
| ✅ Approved | Manually verified by human reviewer |
| ❌ Not an event | Status = **Rejected** (AI will skip this) |
| ❌ Past event | Status = **Rejected** (AI will skip this) |
| ❌ Dead link | Status = **Rejected** (AI will skip this) |

> **Setup:** Run **SPAN-EA AI > Setup > Apply QA Dropdown** once to activate the dropdown menu.

---

## Step 3: AI Processing (Google Sheet)

Go to **SPAN-EA AI > Step 2: Process Pending Data (AI)**

**What the AI does:**
- Rewrites a new Blog Draft in the SPAN-EA editorial voice.
- Categorizes it: Upcoming Event / Industry News.
- Extracts the Event Date.
- Extracts CPD/PDH credits (if any).

**Result:** Status changes to **"Processed"**

---

## Step 4: Flag Upcoming Events (Google Sheet)

Go to **SPAN-EA AI > Step 3: Flag Upcoming Events**

**Result:** Column M (Upcoming Flag) will show:
- 🔔 UPCOMING (30 days) — events happening soon.
- ⏳ Future (>30 days)
- 📅 Past Event

---

## Step 5: Export (Optional — for CSV/HTML backup)

These steps are **optional** if you are using the Direct Push (Step 6). They produce downloadable files for manual import or as a fallback:

- **SPAN-EA AI > Step 5: Export Events (Events.csv)** — Downloads a CSV with columns: `name`, `content`, `website_published`, `post_date`. Sorted newest first.
- **SPAN-EA AI > Step 4: Generate Newsletter (News.html)** — Generates the Newsletter HTML and saves it to a "Newsletter Draft" tab.

---

## Step 6: Push to Odoo — Direct Push ⚡ (Primary Method)

Go to **SPAN-EA AI > Step 6: Push Directly to Odoo ⚡**

### What happens when you click:

1. **Newsletter Safety Prompt:** A popup asks: *"Do you also want to overwrite the Odoo Newsletter page?"*
   - Click **YES** → Push blogs AND overwrite Newsletter HTML.
   - Click **NO** → Push blogs only. Newsletter is protected (manual image/layout edits are safe).

2. **Connects to Odoo** via JSON-RPC using credentials stored in Script Properties.

3. **Chronological Sorting:** The system collects all "Processed" rows, sorts them by Event Date (furthest future first, soonest last), and pushes in that exact order. This guarantees that the soonest events get the highest Odoo IDs and appear at the top of the blog.

4. **Duplicate Detection:** If a post title already exists in Odoo, it is skipped.

5. **`post_date` Field:** Each blog post includes a `post_date` matching the event date, enabling Odoo to display correct chronological order. If the Odoo version rejects this field, the script automatically retries without it.

6. **Draft Mode:** All posts are created as **unpublished drafts** — the admin (Loloa) reviews, adds cover images, and publishes manually.

**Result:** A summary popup shows how many posts were created, skipped, or failed, plus the Newsletter status.

---

## Step 7 (Fallback): Push via Python Script

If Step 6 fails (e.g., API limits), use the Python fallback:

1. Download `Events.csv` (Step 5) and `News.html` (Step 4) from Google Sheets.
2. Place both files in the project folder alongside `push_to_odoo.py`.
3. Ensure `.env` has your Odoo credentials.
4. Run:
   ```bash
   python push_to_odoo.py
   ```

---

## Step 8: Publish & Add Images (Human-in-the-Loop)

1. Go to Odoo → Website app → Site > Blog Posts.
2. Open each newly imported draft. Review the text, then **upload a cover image** using Odoo's Media Library (drag & drop).
3. Toggle the status to **"Published"** when ready.
4. For the Newsletter page: double-click any placeholder image → select a real image from "My Images" (previously uploaded to the Blog). The Media Library shares images across all pages.

> **Why manual images?** Odoo's WYSIWYG editor handles responsive image sizing, cropping, and alignment far better than injecting URLs via API. This ensures the website looks professional on all devices.

---

## Admin Tools

| Tool | Menu Path | Purpose |
|------|-----------|---------|
| Reset Status | SPAN-EA AI > Admin: Reset "Pushed to Odoo" to "Processed" | Bulk reset for re-deployment after testing |
| Set Odoo Credentials | SPAN-EA AI > Setup > Set Odoo Credentials | Store Odoo URL, DB name, username, and password |
| Set Gemini API Key | SPAN-EA AI > Setup > Set Gemini API Key | Store the Gemini API key securely |

---

## 📊 Summary: What is Auto vs Manual

| Step | Auto/Manual | Reason |
|-------|-------------|--------|
| Scrape | ✅ Auto | Python `scrape_events.py` handles this. |
| QA Review | 👤 Manual | Humans ensure quality input. |
| AI Processing | ✅ Auto | Google Gemini generates drafts. |
| Flagging | ✅ Auto | Script calculates dates. |
| Export (CSV+HTML) | 🔘 Optional | Only needed for Python fallback. |
| Push Blog & Newsletter | ✅ Auto | Step 6: Direct Push to Odoo via JSON-RPC. |
| Publish, Images & Tags | 👤 Manual | Human final approval and visual curation. |

**Automation Rate: ~95% (Automated Data Collection, Content Generation, Sorting, and CMS Integration)**
