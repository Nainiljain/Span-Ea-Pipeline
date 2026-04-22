# SPAN-EA AI Content Engine

Automated news/event scraper and AI blog generator for **SPAN-EA (Engineers & Architects in Ontario)**.

## How It Works

```
Python Scraper → Google Sheets + Gemini AI → Odoo CMS (JSON-RPC)
     │                    │                        │
 scrape_events.py    Code.gs (Steps 1-5)    Direct Push (Step 6)
                                               ├─ Blog Posts (Drafts)
                                               └─ Newsletter Page (HTML)
```

## Quick Start

1. **Setup Python:**
   ```bash
   pip install -r requirements.txt
   # Create .env in this folder, then add your Webhook URL + Odoo credentials
   ```

2. **Run Scraper:**
   ```bash
   python scrape_events.py
   ```

3. **Google Sheets (Code.gs):**
   - Open **Extensions > Apps Script** → paste `Code.gs`
   - **SPAN-EA AI > Setup > Set Gemini API Key** → paste your key
   - **SPAN-EA AI > Setup > Set Odoo Credentials** → enter Odoo URL, DB, User, Password
   - **SPAN-EA AI > Setup > Apply QA Dropdown** → activate human review dropdowns
   - **SPAN-EA AI > Setup > Apply Date Picker** → enable calendar in Event Date column

4. **Push to Odoo (Primary — Direct Push):**
   - Click **SPAN-EA AI > Step 6: Push Directly to Odoo ⚡** from Google Sheets
   - A safety prompt will ask whether to also update the Newsletter page
   - Blog posts are created as unpublished drafts, sorted chronologically (soonest event on top)

5. **Push to Odoo (Fallback — Python):**
   ```bash
   python push_to_odoo.py
   ```

See [demo_guide.md](demo_guide.md) for the complete step-by-step demo flow.
See [setup_guide.md](setup_guide.md) for initial setup from scratch.

## Project Files

| File | Purpose |
|------|---------|
| `scrape_events.py` | Python scraper (TSA, Google News for OAA/PEO/OSPE). Supports `--webhook`, `--cache`, and `--dry-run` modes |
| `Code.gs` | Google Apps Script (AI processing, Dead Link Shield, CSV/HTML export, Odoo JSON-RPC push) |
| `push_to_odoo.py` | Fallback: XML-RPC automation. Supports Cache mode (JSON) and CSV mode with interactive per-post review |
| `auto_pipeline.py` | **[Advanced]** Fully automated end-to-end pipeline — scrape, AI enrich, and push to Odoo in one command (bypasses Google Sheets) |
| `requirements.txt` | Python dependencies |
| `.env` | Environment variables for local run and fallback push |
| `demo_guide.md` | Complete demo flow (step-by-step) |
| `setup_guide.md` | Initial setup & installation guide |
| `TECH_SPECS.md` | Technical specifications, architecture, and safeguards |

## Key Features

- **Dynamic Chronological Sorting:** Events are sorted in-memory before pushing to Odoo. Soonest events get the highest IDs, appearing first on the blog page.
- **Dead Link Shield:** Every URL is HTTP-validated during AI processing. Dead links are automatically repaired by Gemini AI or flagged as `❌ Dead link` for human review. All downstream outputs (Newsletter, CSV, Direct Push) skip confirmed dead links.
- **Newsletter Protection Switch:** A safety prompt prevents accidental overwriting of manually-edited Newsletter layouts and images.
- **`post_date` Field:** CSV exports include `post_date` for accurate Odoo import ordering.
- **Human-in-the-Loop QA:** Dropdown menus for standardized human review before AI processing.
- **Admin Reset Tool:** Bulk reset "Pushed to Odoo" statuses back to "Processed" for re-deployment.
- **Full Automation Pipeline (`auto_pipeline.py`):** An advanced, optional script that performs scraping, AI enrichment, and Odoo push in a single command — designed for future use when the sponsor is ready for fully hands-free operation.

## Tech Stack

- **Scraping:** Python 3 + BeautifulSoup + RSS
- **AI:** Google Gemini API (configurable model)
- **Data Hub:** Google Sheets + Apps Script
- **CMS:** Odoo Website (Blog + Newsletter page)
- **Integration:** JSON-RPC (primary, via Apps Script) + XML-RPC (fallback, via Python)
