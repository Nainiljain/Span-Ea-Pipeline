# SPAN-EA Two-Button Deployment Guide
## Deploy the Pipeline API to Railway (Permanent Hosting)

---

## Overview

```
[Odoo Button] → POST → [Railway Flask API] → [Google Sheets + Apps Script + Odoo]
```

Railway hosts the Flask API permanently at a public HTTPS URL.
Your two Odoo buttons call this URL — no laptop running required.

---

## STEP 1 — Generate Token B64 (run locally, one time)

You need to convert your local `token.pickle` into a base64 string
for Railway to use without browser login.

```bash
python generate_token_b64.py
```

Copy the long output string — you'll need it in Step 4.

---

## STEP 2 — Push project to GitHub

1. Go to https://github.com → New repository → name it `span-ea-pipeline`
2. Make it **Private**
3. In your project folder run:

```bash
git init
git add .
git commit -m "SPAN-EA Pipeline v2.0"
git remote add origin https://github.com/YOUR_USERNAME/span-ea-pipeline.git
git push -u origin main
```

> ⚠️  Make sure `.gitignore` excludes `.env`, `token.pickle`, `client_secret.json`

---

## STEP 3 — Create Railway Project

1. Go to https://railway.app → Log in with GitHub
2. Click **New Project** → **Deploy from GitHub repo**
3. Select your `span-ea-pipeline` repository
4. Railway will detect the `Procfile` and deploy automatically

---

## STEP 4 — Set Environment Variables in Railway

In your Railway project → **Variables** tab, add ALL of these:

| Variable | Value |
|---|---|
| `ODOO_URL` | `https://span-ea-capstone.odoo.com` |
| `ODOO_DB` | `span-ea-capstone` |
| `ODOO_USER` | `nainil0512@gmail.com` |
| `ODOO_PASSWORD` | your Odoo password |
| `GAS_SCRIPT_ID` | your Apps Script ID |
| `SPREADSHEET_ID` | your Google Sheet ID |
| `TOKEN_PICKLE_B64` | the long string from Step 1 |

Click **Deploy** after saving variables.

---

## STEP 5 — Get Your Railway URL

After deployment:
1. Railway dashboard → your project → **Settings** tab
2. Copy the public URL, e.g.: `https://span-ea-pipeline.railway.app`

Test it works:
```
https://span-ea-pipeline.railway.app/api/health
```
Should return: `{"status": "ok", ...}`

---

## STEP 6 — Add Buttons to Odoo Pages

### Blog Page Button

1. Go to your Odoo blog page
2. Click **Edit** (top right)
3. Add a new block → **Custom HTML** (or "Code" block)
4. Paste the entire contents of `odoo_blog_button.html`
5. Find the line: `var API_URL = "YOUR_API_URL";`
6. Replace `YOUR_API_URL` with your Railway URL (no trailing slash)
   e.g. `var API_URL = "https://span-ea-pipeline.railway.app";`
7. Click **Save**

### Newsletter Page Button

1. Go to your Odoo newsletter page
2. Repeat steps 2-7 using `odoo_newsletter_button.html`

---

## STEP 7 — Test the Buttons

1. Click **🚀 Run Blog Pipeline** on the blog page
2. Watch the live log — it should show:
   ```
   ✅ Code.gs functions complete
   ✅ Events.csv downloaded
   ✅ Odoo authenticated
   📁 Archived X expired post(s)
   ✅ Done! X new draft(s) created
   ```
3. Go to Odoo backend → Website → Blog Posts to see new drafts
4. Go to Odoo backend → Website → Blog Posts → Archive blog to see archived posts

---

## Maintenance

### Token expires (every 6 months)
Google OAuth tokens expire. To refresh:
1. Run `python full_pipeline.py` locally (browser opens, log in again)
2. Run `python generate_token_b64.py`
3. Update `TOKEN_PICKLE_B64` in Railway variables
4. Redeploy

### Check server logs
Railway dashboard → your project → **Logs** tab

### Redeploy after code changes
```bash
git add .
git commit -m "Update"
git push
```
Railway auto-redeploys on every push.

---

## File Summary

| File | Purpose |
|---|---|
| `full_pipeline.py` | Core pipeline logic (CLI + API mode) |
| `pipeline_api.py` | Flask API server |
| `Procfile` | Tells Railway how to start the server |
| `requirements.txt` | Python dependencies |
| `generate_token_b64.py` | Converts token.pickle → base64 for Railway |
| `odoo_blog_button.html` | Button snippet for Odoo blog page |
| `odoo_newsletter_button.html` | Button snippet for Odoo newsletter page |
