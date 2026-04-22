# 🚀 SPAN-EA Capstone: Complete Setup Guide

**Goal:** Set up a fresh Odoo site and demonstrate the end-to-end AI Content Automation Pipeline.
**What we automate:** Blog posts + Newsletter — matching the real SPAN-EA website (`span-ea.ca/blog` and `span-ea.ca/our-services`).

---

## Phase 1: Create Odoo Account (5 min)

1. Go to `odoo.com` → Click **"Start Now - It's Free"**.
2. On the **first screen**, select ONLY **1 app**: `Website`.
   - **Blog is included automatically** — it's a built-in feature of Website, not a separate app.
   - Selecting 1 app = **free forever, unlimited users**.
3. Fill in your details. Call the company something like `span-ea-demo`.
4. Check your email inbox → Click the activation link.
5. Create a password. You are now the Admin.

**Result:** You now have **Website** (includes Blog).
No need for Email Marketing or Events — we don't use them.

### Create the Newsletter Page
1. Go to **Website** app → click **+ New** (top right) → select **Page**.
2. Name it **`Newsletter`** → click **Create**.
3. Click **Edit** → in the right sidebar, scroll to **"Embed Code"** (under Inner Content).
4. **Drag** the Embed Code block onto the page → click **Save**.
5. Odoo will generate a URL like `/newsletter` or `/newsletter-1` — don't worry about the exact name, the automation script finds it automatically.

---

## Phase 2: Set Up Google Sheet + Python Scraper

### Python Side
1. Clone the project: `git clone <repo-url>`
2. Create a new `.env` file in the project root
3. Add your Google Script Webhook URL to `.env`:
   ```
   SPAN_EA_WEBHOOK_URL=https://script.google.com/macros/s/YOUR_ID/exec
   ```
4. Add your Odoo credentials to `.env` (used by the Python fallback script):
   ```
   ODOO_URL=https://your-site.odoo.com
   ODOO_DB=your-database-name
   ODOO_USER=your-email@example.com
   ODOO_PASSWORD=your-password
   ```
5. Install dependencies: `pip install -r requirements.txt`

### Google Sheet Side
1. **Recommended:** Prepare one master Google Sheet Prototype (template) with all required tabs/headers, then share a **Make a copy** link to users.
   - **Current Prototype (Make a copy):** https://docs.google.com/spreadsheets/d/1AEuzDdNTFhaYT5l37ESgq8EUS5DP9T1WPGL1ojjQNik/copy
2. In the Prototype, set columns A-M on `Sheet1` exactly as:
   `Date Scraped | Source | Original Title | Original Content | URL | Status | QA Notes | AI Category | Event Date | AI Title | CPD Info | Generated Blog Draft | Upcoming Flag`
3. In the Prototype, create a `Config` tab and add Named Range `GenEveryDays` = `14`
4. Open **Extensions > Apps Script** in the Prototype sheet and paste the entire `Code.gs`
5. Run the following setup steps from the **SPAN-EA AI** menu:
   - **Setup > Set Gemini API Key** → paste your key from Google AI Studio
   - **Setup > Set Odoo Credentials** → enter your Odoo URL, database name, username, and password
   - **Setup > Apply Date Picker** → enable calendar date selection on Column I
   - **Setup > Apply QA Dropdown** → enable the QA validation dropdown on Column G
6. Deploy the script as a Web App (Execute as: Me, Access: Anyone) → copy the Webhook URL to `.env`

### After User Clicks "Make a copy" (Important)
1. Rename the spreadsheet file (recommended):
   - Example: `SPAN-EA Pipeline - Team A` or `SPAN-EA Pipeline - ClientName`
2. **Do not rename these tabs** unless you also update `Code.gs`:
   - `Sheet1`
   - `Config`
3. Keep the A-M headers exactly the same on `Sheet1`.
4. In the copied sheet, run setup again from **SPAN-EA AI** menu:
   - Setup: Set Gemini API Key
   - Setup: Set Odoo Credentials
   - Setup: Apply Date Picker to Column I
   - Setup: Apply QA Dropdown to Column G
5. Re-deploy the Apps Script Web App from the copied sheet and use its webhook URL in `.env`:
   - `SPAN_EA_WEBHOOK_URL=...`

---

## Phase 3: Run the Pipeline

### Step 1: Scrape
```bash
python scrape_events.py
```
Data flows into Google Sheet automatically via webhook.

### Step 2: QA (Human Review)
- New rows appear as **"Pending"** in Column F.
- Use the QA Dropdown in Column G to approve or reject each row.
- If a link is bad → select **"❌ Dead link"** → status flips to **"Rejected"** automatically.

### Step 3: AI Processing
- Go to **SPAN-EA AI > Step 2: Process Pending Data (AI)**
- Watch AI generate blog drafts, categories, and dates.

### Step 4: Flag Events
- Go to **SPAN-EA AI > Step 3: Flag Upcoming Events**
- Events within 30 days get flagged as **"🔔 UPCOMING"**.

### Step 5: Generate Newsletter (Optional)
- Go to **SPAN-EA AI > Step 4: Generate Newsletter (News.html)**
- HTML is saved to a "Newsletter Draft" tab in the sheet.

---

## Phase 4: Push to Odoo

### Primary Method: Direct Push (Step 6)

This is the **recommended** method. It pushes directly from Google Sheets to Odoo with no file downloads needed.

1. Go to **SPAN-EA AI > Step 6: Push Directly to Odoo ⚡**
2. A safety prompt will appear: **"Do you also want to overwrite the Odoo Newsletter page?"**
   - Click **YES** to update both Blog posts and Newsletter.
   - Click **NO** to push only Blog posts (protects any manual image/layout edits on the Newsletter page).
3. The script will:
   - Connect to Odoo via JSON-RPC
   - Sort events chronologically (soonest events appear at the top of the blog)
   - Create each post as an **unpublished draft** with a `post_date` matching the event date
   - Skip any duplicate post titles
   - Show a summary popup when finished

### Fallback Method: Python Script

If the Direct Push encounters issues, use the Python fallback:

1. Export the data from Google Sheets:
   - **SPAN-EA AI > Step 5: Export Events (Events.csv)** → download the CSV
   - **SPAN-EA AI > Step 4: Generate Newsletter (News.html)** → download the HTML
2. Place both files in the same folder as `push_to_odoo.py`.
3. Run:
   ```bash
   python push_to_odoo.py
   ```

### Future Use: Full Automation (`auto_pipeline.py`)

When confident in the AI's output, you can bypass Google Sheets completely:
1. Ensure `GEMINI_API_KEY` is set in `.env`
2. Run: `python auto_pipeline.py`
This performs scraping, AI enrichment, and Direct Push in one step.

### Admin: Reset for Re-deployment

If you need to re-push events (e.g., after deleting test posts from Odoo):
- Go to **SPAN-EA AI > Admin: Reset "Pushed to Odoo" to "Processed"**
- This bulk-resets all "Pushed to Odoo" statuses so they can be pushed again.

---

## Phase 5: Publish & Add Images (Human-in-the-Loop)

1. Go to your Odoo site → **Website > Site > Blog Posts**
2. Open each draft post:
   - Review the AI-generated text
   - **Upload a cover image** using Odoo's drag-and-drop Media Library
   - Assign Tags (e.g., IT, Architecture)
   - Toggle **"Published"** when ready
3. For the Newsletter page:
   - Open the Newsletter page in Odoo's Website Builder
   - Double-click any placeholder image → select a real image from **"My Images"** (images uploaded to Blog posts are automatically available here)
   - Save when done

> **💡 Tip:** Upload images once when editing Blog posts. The same images can be reused on the Newsletter page via Odoo's shared Media Library — no re-uploading needed!

---

## Phase 6: Verify

Open your Odoo site and check:
- [ ] `/blog` — AI-generated posts are listed, sorted with soonest events at the top
- [ ] `/newsletter-1` — Newsletter HTML renders correctly with event cards
- [ ] Blog posts are in **Draft mode** until you manually publish them
- [ ] Navigation menu shows: Home | Blog | Newsletter
