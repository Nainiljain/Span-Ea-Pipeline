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
1. Install **Python 3.10 or higher** (if not already installed):
   - Download from 👉 https://python.org/downloads
   - During installation, check **"Add Python to PATH"**
   - Verify it works by running: `python --version` (should show 3.10+)

2. Clone the project:
   ```bash
   git clone https://github.com/Nainiljain/Span-Ea-Pipeline.git
   cd Span-Ea-Pipeline
   ```
2. Install dependencies:
   ```bash
   pip install -r requirements.txt
   ```
3. Create a `.env` file in the project root with the following values:
   ```
   ODOO_URL=https://your-site.odoo.com
   ODOO_DB=your-database-name
   ODOO_USER=your-email@example.com
   ODOO_PASSWORD=your-odoo-password
   GAS_SCRIPT_ID=your-apps-script-id
   SPREADSHEET_ID=your-google-sheet-id
   SPAN_EA_WEBHOOK_URL=https://script.google.com/macros/s/YOUR_ID/exec
   ```

---

### 🔑 Where to Get Each Credential

#### ODOO_URL / ODOO_DB / ODOO_USER / ODOO_PASSWORD
These come from your existing Odoo account (provided by the sponsor/admin):
- `ODOO_URL` — the URL you use to log in to Odoo, e.g. `https://spanea.odoo.com`
- `ODOO_DB` — the database name, usually the part before `.odoo.com`, e.g. `spanea`
- `ODOO_USER` — your Odoo login email
- `ODOO_PASSWORD` — your Odoo login password

#### SPREADSHEET_ID — from Google Sheets URL
1. Click the link below to copy the template sheet:
   👉 https://docs.google.com/spreadsheets/d/1AEuzDdNTFhaYT5l37ESgq8EUS5DP9T1WPGL1ojjQNik/copy
2. After copying, look at the URL of your new sheet:
   ```
   https://docs.google.com/spreadsheets/d/[ THIS PART IS YOUR SPREADSHEET_ID ]/edit
   ```
3. Copy that ID into your `.env` file.

#### GAS_SCRIPT_ID — from Google Apps Script
1. In your copied Google Sheet, click **Extensions > Apps Script**
2. Delete any existing code, then paste the entire contents of `Code.gs` from this repo
3. Press **`Ctrl+S`** and name the project `SPAN-EA Pipeline`
4. Click the **⚙️ Project Settings** icon (left sidebar)
5. Scroll down to find **Script ID** — copy it into your `.env` as `GAS_SCRIPT_ID`

#### SPAN_EA_WEBHOOK_URL — Deploy as Web App (required for scraper)
> ⚠️ Without this, `scrape_events.py` will only save to local cache and **nothing will appear in Google Sheets**

1. In Apps Script, click **Deploy > New Deployment**
2. Click the ⚙️ gear icon → select **Web App**
3. Set **Execute as:** `Me`
4. Set **Who has access:** `Anyone`
5. Click **Deploy** → copy the URL (format: `https://script.google.com/macros/s/.../exec`)
6. Add to your `.env`:
   ```
   SPAN_EA_WEBHOOK_URL=https://script.google.com/macros/s/YOUR_ID/exec
   ```

#### OAUTH_CLIENT_SECRET_JSON — (Optional) for running `full_pipeline.py`
> ℹ️ **Only needed if** you want Python to control Google Sheets entirely without opening a browser (headless/automated mode via `full_pipeline.py`). Not required for the standard Google Sheets menu workflow.

1. Go to 👉 https://console.cloud.google.com → Create a new project
2. Go to **APIs & Services > Library** → Enable:
   - **Google Apps Script API**
   - **Google Sheets API**
3. Go to **APIs & Services > OAuth consent screen**
   - User Type: **External** → click Create
   - Fill in App name (e.g. `SPAN-EA Pipeline`) and support email → click Next through all steps
4. Go to **APIs & Services > Credentials**
   - Click **+ CREATE CREDENTIALS > OAuth client ID**
   - Application type: **Desktop app** → click Create
5. Click **Download JSON** → rename to `client_secret.json` → place in project folder

> ⚠️ Never commit `client_secret.json` to Git — it is already in `.gitignore`

#### Gemini API Key — stored in Google Sheets (not in .env)
The Gemini key is stored securely inside Google Sheets Script Properties, not in `.env`.
1. Go to 👉 https://aistudio.google.com/apikey
2. Click **Create API key** and copy it
3. In your Google Sheet, click **SPAN-EA AI > Setup > Set Gemini API Key** and paste the key

---

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
- **💡 Tip: Find Pending rows fast** — Click the filter icon (▼) on the **Status** column header → **Filter by value** → select `Pending` only. This hides all already-processed rows so you see only what needs review. Alternatively, use **Filter by color** if the sheet has conditional formatting.
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

---

## 🤖 Changing the AI Model

By default the pipeline uses `gemini-2.0-flash` (free tier). If you hit rate limits or want better quality, change the model name in **2 files only**:

### File 1: `Code.gs` (line ~28)
```javascript
const AI_MODEL_NAME = "gemini-2.0-flash";  // ← change this
```

### File 2: `auto_pipeline.py` (line ~53)
```python
AI_MODEL = "gemini-2.0-flash"  # ← change this
```

### Available Model Options

| Model Name | Cost | Notes |
|---|---|---|
| `gemini-2.0-flash-lite` | Free | Lowest limit, for testing |
| `gemini-2.0-flash` | Free | **Default** |
| `gemini-3.1-flash-lite-preview` | Free | Higher throughput, fewer rate limit errors |
| `gemini-2.5-flash` | Free (new tier) | Improved quality |
| `gemini-2.5-pro` | 💰 Paid | Best quality, for production use |

> **Note:** To use a non-Gemini AI provider (e.g., OpenAI, Claude), the API call logic inside both `Code.gs` and `auto_pipeline.py` must also be updated — not just the model name.

---

## 🛠️ Troubleshooting

### ❌ Problem: Rows with "✅ Approved" in QA Notes show "Rejected" in Status

**Why it happens:** Old versions of `Code.gs` used a formula in the Status column that treated *any* non-blank QA value (including Approved) as Rejected.

**Fix (already built-in to Code.gs v3.3+):** The `onEdit` function now watches the QA Notes column. The moment you select a value from the dropdown, Status updates automatically:

| QA Notes selected | Status becomes |
|---|---|
| ✅ Approved | **Pending** (AI will process it) |
| ❌ Not an event / ❌ Past event / ❌ Dead link | **Rejected** |
| Cleared (empty) | **Pending** |
| Already "Processed" or "Pushed to Odoo" | *(not changed)* |

> ✅ No manual step needed — just select from the dropdown and Status updates instantly.

If you are upgrading from an older `Code.gs`, paste the latest version into Apps Script and press **Ctrl+S**. Existing rows with the wrong Status can be fixed by re-selecting their QA Notes value from the dropdown.


---

### ❌ Problem: Scraper runs but nothing appears in Google Sheets

**Why it happens:** `SPAN_EA_WEBHOOK_URL` is missing or incorrect in your `.env` file. The scraper defaults to local cache mode.

**Fix:**
1. Deploy Apps Script as a Web App (see [GAS Setup](#gas_script_id--from-google-apps-script) above)
2. Copy the deployment URL
3. Add to `.env`: `SPAN_EA_WEBHOOK_URL=https://script.google.com/macros/s/YOUR_ID/exec`
4. Re-run: `python scrape_events.py --webhook`

---

### ❌ Problem: Step 2 (AI Processing) stops early or shows "Execution time limit"

**Why it happens:** Google Apps Script has a 6-minute execution limit. Large batches hit this limit.

**Fix:** Simply run **Step 2** again — it skips already-processed rows and continues from where it left off.

