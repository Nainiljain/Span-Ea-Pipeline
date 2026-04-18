# SPAN-EA AI Content Engine: Technical Specifications & Safeguards

This document explains the technical architecture, data pipeline resilience, and the core enterprise safeguards built into Version 3.2 (Dead Link Shield). It serves as a reference for technical Q&A and system architecture review.

## 🏗️ System Overview
The system is built for maximum resilience, ensuring bad data does not break the automation pipeline and that API costs are strictly controlled.

---

## Part 1: Data Ingestion (Python Scraper)

### File: `scrape_events.py` (v2.0 — Dual Output Mode)
**Objective:** Gathers relevant articles while bypassing bot-protected websites.

1.  **Dual Output Mode:** The scraper supports two output modes via CLI flags:
    *   `--webhook` (Mode A): Sends scraped data directly to Google Sheets via Apps Script webhook (original flow).
    *   `--cache` (Mode B): Saves scraped data to `pipeline_cache_raw.json` for use by `auto_pipeline.py` or `push_to_odoo.py`.
    *   `--dry-run`: Scrape and print results without saving anything (for testing).
    *   **Auto-detect:** If no flag is specified, the scraper checks for a webhook URL in `.env` — sends to webhook if found, otherwise saves to cache.
2.  **Environment Settings:** The script reads `SPAN_EA_WEBHOOK_URL` from a local `.env` file for security, keeping webhooks out of source control.
3.  **Scraping Strategy (WAF Bypass):**
    *   **TSA (Toronto Society of Architects):** Uses a dual-strategy (Primary HTML Scraping + RSS Fallback) to ensure 100% data availability even if the main site structure changes.
    *   **Google News RSS Engine:** Queries `site:peo.on.ca after:YYYY-MM-DD` to bypass Cloudflare and Web Application Firewalls (WAF) that typically block generic python requests on institutional sites.
4.  **Content Enrichment:** For every link found, the script attempts to visit the URL and extract the full body text (`<p>` tags) to provide Gemini with maximum context.
5.  **Deduplication (Local):** A local memory set (`seen_keys`) ensures no duplicate titles or identical URLs are sent in a single batch.
6.  **Fail-Safe Networking:** Features built-in timeouts (`REQUEST_TIMEOUT = 15`) and retry logic to handle intermittent internet lag.

---

## Part 2: Spreadsheet Logic (Google Apps Script)

### File: `Code.gs`
The backend data hub is powered by Google Apps Script, acting as the middleware between Python and Odoo.

### 🛡️ Core Enterprise Safeguards

#### Safeguard 1: Duplicate URL Rejection (doPost)
*   Handles incoming data from Python.
*   **Duplicate Detection:** Scans Column E (URL). If the link already exists in the database from a previous run, the webhook instantly skips the row, preventing database bloat.
*   **Dynamic Column Mapping:** Reads headers mathematically to find "QA Notes" and "Status". It works dynamically even if columns are moved by human administrators.

#### Safeguard 2: Smart Timeout Guard (processDataRowByRow)
*   Monitors execution time. Google Apps Script has a strict 6-minute execution limit. If the AI processing approaches the 5-minute mark (300,000ms), the script pauses gracefully: `ui.alert("Execution time limit approaching...")` and saves state.
*   **Rate Limiting:** Features a strict 6-second delay (`Utilities.sleep(6000)`) between rows to respect Google Gemini's free-tier Requests-Per-Minute (RPM) limits.

#### Safeguard 3: Automatic Style Scrubber (onEdit Magic)
*   **The Magic Scrub:** When a human QA tester copies and pastes data directly into the sheet (e.g., overriding a date), the `onEdit` trigger instantly activates.
*   **Action:** It strips all aggressive HTML styling, background colors, and font sizes injected from external websites, immediately restoring the SPAN-EA clean corporate aesthetic.

#### Safeguard 4: Smart Date Parsing (smartParseDate)
*   A local helper function cleans messy strings (e.g., "Monday, June 10th") into valid native Date objects without calling external APIs.
*   **Zero Token Cost:** Strips names ("Monday", "Tue") and ordinals ("st", "nd", "th") using Regex instead of wasting AI tokens on simple string manipulation.

#### Safeguard 5: Cost & Token Protection
1.  **Human QA First:** Humans reject dead links, 404s, or junk news *before* the API is ever called. The status is set to "Rejected" ensuring zero wasted tokens.
2.  **Pre-Fill Logic:** If a human types a date into the "Event Date" column, the script passes this directly to the AI as a "Critical Instruction", bypassing the need for the AI to guess the date from text context.

#### Safeguard 6: QA Dropdown Validation
*   Column G ("QA Notes") features a programmatic dropdown menu with standardized options: `✅ Approved`, `❌ Not an event`, `❌ Past event`, `❌ Dead link`.
*   Activated via **SPAN-EA AI > Setup > Apply QA Dropdown**. This ensures consistent human review inputs and prevents free-text ambiguity.

#### Safeguard 7: Chronological Sort Order
*   The CSV export function (`exportCSVForOdoo`) automatically sorts all exportable rows by Event Date in **descending order (newest first)** before generating the file.
*   The CSV includes a `post_date` column, allowing Odoo to display the correct event date instead of the upload date.
*   This ensures Odoo blog posts are imported in the correct chronological sequence, with the most relevant upcoming events appearing first.

#### Safeguard 8: Admin Reset Tool & Duplicate Protection
*   Menu item **SPAN-EA AI > Admin: Reset "Pushed to Odoo" to "Processed"** bulk-resets all rows with status "Pushed to Odoo" back to "Processed".
*   **Zero-Damage Safety:** If accidentally clicked, it causes no harm. When "Direct Push to Odoo" is subsequently run, the script's built-in **Duplicate Detection** queries the Odoo database (`blog.post` titles) and automatically skips any posts that already exist, preventing duplicate entries.
*   This allows safe re-deployment after testing, fixing data, or deleting test posts from Odoo without manually editing each row.

#### Safeguard 9: `post_date` Fallback Retry
*   When pushing to Odoo via JSON-RPC, the script includes a `post_date` field in the `blog.post` create payload.
*   If the Odoo instance rejects this field (some versions/configurations do not accept `post_date` via external API), the script automatically catches the error, removes `post_date` from the payload, and retries the push.
*   This ensures zero data loss regardless of the Odoo version deployed.

#### Safeguard 10: Dead Link Shield (URL Validator + AI Auto-Fix)
*   During AI processing (Step 2), every URL in the spreadsheet is HTTP-checked using `isUrlAlive()` — a real HTTP request that verifies the link returns a 200-399 status code.
*   **AI Auto-Fix:** If a URL is dead, the system calls `findWorkingUrlWithGemini()` — asking Gemini AI to suggest a working replacement URL based on the event title, source, and content. The suggested URL is verified before being applied.
*   **Graceful Degradation:** If AI cannot find a working replacement, the row is flagged as `❌ Dead link` in the QA Notes column for human review.
*   **Downstream Protection:** All downstream outputs — Newsletter (Step 4), CSV Export (Step 5), and Direct Push (Step 6) — automatically skip rows marked with confirmed dead links, ensuring zero broken links reach the live website.

---

## Part 3: Architecture Integration (Odoo CMS)

### The "Direct Push" (Google Apps Script JSON-RPC)
**Objective:** Eliminate copy-pasting of HTML and manual blog imports by pushing directly from Google Sheets to Odoo.

1. **Direct JSON-RPC Integration:** Bypasses front-end scraping to talk directly to the Odoo PostGreSQL database via securely authenticated JSON-RPC calls from within `Code.gs`.
2. **Dynamic Chronological Sorting:** The script dynamically parses all event dates and sorts them in memory (Furthest Future to Soonest). It pushes the furthest events first (lowest ID) and the soonest events last (highest ID). Because Odoo sorts natively by ID Descending, this guarantees that tomorrow's events appear at the very top of the blog.
3. **Incremental Draft System:** Checks database IDs against post names. Uniquely creates new articles as **Unpublished Drafts** (protecting the live site from accidental automated publishing and allowing human layout edits).
4. **Newsletter Protection Switch:** Features a built-in safety prompt that asks the user if they want to overwrite the Newsletter page (`website.page`). If the user clicks "NO", it safely pushes blogs while shielding the Newsletter from losing any manual image or layout adjustments.

### Fallback System: `push_to_odoo.py` (v2.0 — Dual Mode)
If Google Apps Script encounters external API limits or Odoo changes its payload requirements, the system gracefully falls back to a local Python XML-RPC script (`push_to_odoo.py`) which supports two input modes:
*   **Mode A (Cache):** Reads `pipeline_cache.json` produced by `auto_pipeline.py`, with per-post interactive review (`[P]ublish / [S]ave draft / [D]iscard`).
*   **Mode B (CSV):** Reads `Events.csv` + `News.html` exported from Google Sheets (original flow).
*   Supports `--no-confirm` (auto-save all as drafts), `--publish-all` (auto-publish everything), and `--cleanup` (unpublish posts no longer in CSV).

### Full Automation Pipeline: `auto_pipeline.py` (Advanced / Future Use)
An optional, fully autonomous Python script that performs the entire pipeline in a single command — scraping, AI enrichment, URL validation, and Odoo push — without requiring Google Sheets. Designed for future use when the sponsor is confident in the AI output quality and ready for hands-free operation.
*   **Usage:** `python auto_pipeline.py` (full pipeline), `--push-only` (skip scraping), `--scrape-only` (no push), `--no-confirm` (auto-draft all).
*   **Note:** This script bypasses the Human-in-the-Loop QA review. The recommended production workflow remains the Google Sheets pipeline (Steps 1-6) for quality control.

### Image Workflow (Design Decision)
Images are intentionally **not** injected via API. Instead, the system creates blog posts with text content only and relies on the Odoo WYSIWYG Website Builder for image management. This is by design because:
1.  Odoo's `cover_properties` field uses a complex JSON structure that varies across versions.
2.  Odoo's Media Library handles responsive sizing, cropping, and CDN delivery automatically.
3.  Images uploaded to one Blog post are available across all pages (including Newsletter) via the shared **"My Images"** tab, eliminating redundant uploads.
