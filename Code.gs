/**

// ── Headless API execution helper ─────────────────────────────────────────
// When called via Apps Script Execution API, UI functions crash.
// Use safeAlert() and safeShowDialog() instead of safeAlert()/showModalDialog()
function isHeadless() {
  try { SpreadsheetApp.getUi(); return false; } catch(e) { return true; }
}
function safeAlert(msg) {
  if (isHeadless()) { Logger.log('[HEADLESS] ' + msg); return; }
  safeAlert(msg);
}
function safeShowDialog(html, title) {
  if (isHeadless()) { Logger.log('[HEADLESS] Dialog skipped: ' + title); return; }
  SpreadsheetApp.getUi().showModalDialog(html, title);
}
// ──────────────────────────────────────────────────────────────────────────

 * Project: SPAN-EA AI Content Engine (Version 3.2 - Dead Link Shield)
 *
 * FIXES IN THIS VERSION:
 * - Fixed AI model name (was "gemini-3.1-flash-lite-preview" which doesn't exist)
 * - Added URL validation: every link is HTTP-checked before being used
 * - Dead links auto-fixed via Gemini; unfixable ones flagged in QA Notes
 * - Newsletter and CSV export skip rows with confirmed dead links
 * - Odoo push skips dead-link rows to prevent broken "Source" links
 * - exportCSVForOdoo also skips dead-link rows
 *
 * COLUMN LAYOUT (Traditional A-M):
 * A: Date Scraped | B: Source | C: Original Title | D: Original Content | E: URL
 * F: Status       | G: QA Notes
 * H: AI Category  | I: Event Date | J: AI Title | K: CPD Info | L: Generated Blog Draft | M: Upcoming Flag
 */

const SCRIPT_PROP_KEY = 'GEMINI_API_KEY';

/**
 * Change the Gemini model here if needed.
 * Valid options: "gemini-2.0-flash", "gemini-2.5-flash", "gemini-2.0-flash-lite"
 */
const AI_MODEL_NAME = "gemini-2.0-flash";


// ─────────────────────────────────────────────────────────
// SECTION 1: SYSTEM HOOKS (onOpen, doPost, onEdit)
// ─────────────────────────────────────────────────────────

function onOpen() {
  const ui = isHeadless() ? null : SpreadsheetApp.getUi();
  ui.createMenu('SPAN-EA AI')
      .addItem('Step 2: Process Pending Data (AI)', 'processDataRowByRow')
      .addItem('Step 3: Flag Upcoming Events', 'flagUpcomingEvents')
      .addSeparator()
      .addItem('Step 4: Generate Newsletter (News.html)', 'generateWeeklyPulse')
      .addItem('Step 5: Export Events (Events.csv)', 'exportCSVForOdoo')
      .addItem('Step 6: Push Directly to Odoo ⚡', 'pushToOdooDirectly')
      .addSeparator()
      .addItem('Setup: Set Gemini API Key', 'setGeminiApiKey')
      .addItem('Setup: Set Odoo Credentials', 'setOdooCredentials')
      .addItem('Setup: Apply Date Picker to Column I', 'applyDatePicker')
      .addItem('Setup: Apply QA Dropdown to Column G', 'applyQADropdown')
      .addItem('Debug: Test API Connection', 'debugGeminiAPI')
      .addSeparator()
      .addItem('Admin: Reset "Pushed to Odoo" to "Processed"', 'resetPushedToProcessed')
      .addToUi();
}

/**
 * AUTO-CLEANER: Runs on every edit.
 * Removes messy website styles/fonts when pasting into the Event Date column.
 */
function onEdit(e) {
  if (!e) return;
  const range  = e.range;
  const sheet  = range.getSheet();
  const column = range.getColumn();
  const row    = range.getRow();

  if (sheet.getName() === "Config" || row === 1) return;

  const headers = sheet.getRange(1, 1, 1, sheet.getLastColumn()).getValues()[0];
  const dateColIdx = headers.findIndex(h => h.toString().trim().toLowerCase() === "event date");

  if (column === (dateColIdx + 1)) {
    range.clearFormat();
    range.setNumberFormat("MMMM d, yyyy");
    range.setHorizontalAlignment("center");
  }
}

/**
 * WEBHOOK: Receives data posted by the Python scraper.
 */
function doPost(e) {
  try {
    const sheet = SpreadsheetApp.getActiveSpreadsheet().getActiveSheet();
    const body  = JSON.parse(e.postData.contents);
    const data  = body.data;
    const timestamp = new Date().toLocaleString();

    const existingData = sheet.getDataRange().getValues();
    const existingURLs = new Set();
    for (let i = 1; i < existingData.length; i++) {
      const url = existingData[i][4] ? existingData[i][4].toString().trim() : "";
      if (url) existingURLs.add(url);
    }

    let addedCount = 0;
    data.forEach(item => {
      const link = (item.link || "").trim();
      if (existingURLs.has(link)) return;

      const newRowIdx = sheet.getLastRow() + 1;
      const headers = sheet.getRange(1, 1, 1, sheet.getLastColumn()).getValues()[0]
                           .map(h => h.toString().trim().toLowerCase());
      const rowData = new Array(headers.length).fill("");

      const setCol = (name, value) => {
        const idx = headers.indexOf(name.toLowerCase());
        if (idx !== -1) rowData[idx] = value;
      };

      setCol("Date Scraped",     timestamp);
      setCol("Source",           item.source);
      setCol("Original Title",   item.title);
      setCol("Original Content", item.content);
      setCol("URL",              link);

      // Single-Touch QA Formula Injection
      const qaColIdx = headers.indexOf("qa notes");
      if (qaColIdx !== -1) {
        const qaLetter = columnToLetter(qaColIdx + 1);
        setCol("Status", `=IF(ISBLANK(${qaLetter}${newRowIdx}), "Pending", "Rejected")`);
      } else {
        setCol("Status", "Pending");
      }

      sheet.appendRow(rowData);
      existingURLs.add(link);
      addedCount++;
    });

    return ContentService
      .createTextOutput(`Success: ${addedCount} added`)
      .setMimeType(ContentService.MimeType.TEXT);
  } catch (err) {
    return ContentService
      .createTextOutput("Error: " + err.toString())
      .setMimeType(ContentService.MimeType.TEXT);
  }
}


// ─────────────────────────────────────────────────────────
// SECTION 2: CORE AI LOGIC (Process & Flag)
// ─────────────────────────────────────────────────────────

function processDataRowByRow() {
  const startTime = Date.now();
  const ui    = isHeadless() ? null : SpreadsheetApp.getUi();
  const sheet = SpreadsheetApp.getActiveSpreadsheet().getActiveSheet();
  const values = sheet.getDataRange().getValues();

  if (values.length < 2) {
    safeAlert("No data found. Please run the Python scraper first.");
    return;
  }

  const headers = values[0].map(h => h.toString().trim().toLowerCase());

  const col = {
    source:    headers.indexOf("source"),
    title:     headers.indexOf("original title"),
    content:   headers.indexOf("original content"),
    url:       headers.indexOf("url"),
    status:    headers.indexOf("status"),
    category:  headers.indexOf("ai category"),
    eventDate: headers.indexOf("event date"),
    aiTitle:   headers.indexOf("ai title"),
    cpdInfo:   headers.indexOf("cpd info"),
    blog:      headers.indexOf("generated blog draft"),
    qa:        headers.indexOf("qa notes")
  };

  let triedCount = 0, processedCount = 0, failedCount = 0;

  for (let i = 1; i < values.length; i++) {
    const rawStatus = values[i][col.status]
      ? values[i][col.status].toString().trim().toLowerCase()
      : "";

    // Only process rows that are NOT already processed or rejected
    if (rawStatus === "processed" || rawStatus === "rejected") continue;

    const sourceVal = (values[i][col.source] || "").toString().trim();
    const titleVal  = (values[i][col.title]  || "").toString().trim();
    if (!sourceVal || !titleVal) continue; // Skip truly empty rows

    triedCount++;
    const content    = values[i][col.content] || "";
    const manualDate = values[i][col.eventDate]
      ? values[i][col.eventDate].toString().trim()
      : "";

    // ── STEP 1: Call Gemini to generate blog content ──
    const aiResultObj = callGeminiAPI(titleVal, content, sourceVal, manualDate);
    if (aiResultObj.error) {
      sheet.getRange(i + 1, col.status + 1).setValue("API Error: " + aiResultObj.error);
      failedCount++;
      continue;
    }
    const aiResult = aiResultObj.result;

    // ── STEP 2: Parse the AI-returned date ──
    let finalDate = smartParseDate(aiResult.eventDate);
    if (!finalDate && aiResult.eventDate !== "Date TBD") {
      Logger.log("AI returned unparseable date: " + aiResult.eventDate);
    }

    // ── STEP 3: Write AI results to sheet ──
    if (col.category  !== -1) sheet.getRange(i + 1, col.category  + 1).setValue(aiResult.category);
    if (col.eventDate !== -1) sheet.getRange(i + 1, col.eventDate + 1).setValue(finalDate || aiResult.eventDate);
    if (col.blog      !== -1) sheet.getRange(i + 1, col.blog      + 1).setValue(aiResult.blogDraft);
    if (col.aiTitle   !== -1) sheet.getRange(i + 1, col.aiTitle   + 1).setValue(aiResult.aiTitle);
    if (col.cpdInfo   !== -1) sheet.getRange(i + 1, col.cpdInfo   + 1).setValue(aiResult.cpdInfo || "Not specified");

    // ── STEP 4: Validate URL — fix dead links using Gemini ──
    if (col.url !== -1) {
      const rawUrl = (values[i][col.url] || "").toString().trim();
      if (rawUrl) {
        const urlCheck = checkAndFixUrl(rawUrl, titleVal, content, sourceVal);
        if (urlCheck.wasFixed) {
          // AI found a working replacement — update the URL cell
          sheet.getRange(i + 1, col.url + 1).setValue(urlCheck.url);
          Logger.log("🔧 Row " + (i + 1) + ": URL auto-fixed → " + urlCheck.url);
        } else if (!urlCheck.isAlive) {
          // Dead link, Gemini could not fix — flag for human QA
          if (col.qa !== -1) {
            const existingNote = (values[i][col.qa] || "").toString().trim();
            if (!existingNote) {
              sheet.getRange(i + 1, col.qa + 1).setValue("❌ Dead link");
            }
          }
          Logger.log("⚠️ Row " + (i + 1) + ": unfixable dead link: " + rawUrl);
        }
      }
    }

    // ── STEP 5: Mark as Processed ──
    if (col.status !== -1) sheet.getRange(i + 1, col.status + 1).setValue("Processed");

    SpreadsheetApp.flush();
    processedCount++;

    // Time guard — Apps Script has a 6-minute execution limit
    if (Date.now() - startTime > 300000) {
      safeAlert("Execution time limit approaching. Pausing. Please run Step 2 again to continue.");
      break;
    }
    Utilities.sleep(6000); // Rate-limit guard (≈10 req/min)
  }

  const duration = ((Date.now() - startTime) / 1000).toFixed(1);
  safeAlert(
    `SPAN-EA AI Processing Complete!\n\n` +
    `📂 Rows Scanned: ${values.length - 1}\n` +
    `🎯 Rows Attempted: ${triedCount}\n` +
    `✅ Success: ${processedCount}\n` +
    `❌ Failed: ${failedCount}\n` +
    `🔗 URLs validated — dead links flagged in QA Notes column\n` +
    `⏱️ Time: ${duration}s`
  );
}

function flagUpcomingEvents() {
  const ui    = isHeadless() ? null : SpreadsheetApp.getUi();
  const sheet = SpreadsheetApp.getActiveSpreadsheet().getActiveSheet();
  const values = sheet.getDataRange().getValues();

  if (values.length < 2) {
    safeAlert("No data found. Run the scraper and AI processor first.");
    return;
  }

  const headers  = values[0].map(h => h.toString().trim().toLowerCase());
  const colDate   = headers.indexOf("event date");
  const colStatus = headers.indexOf("status");
  const colFlag   = headers.indexOf("upcoming flag") !== -1
    ? headers.indexOf("upcoming flag")
    : 12; // Default to column M (0-indexed = 12)

  let lookAheadDays = 14;
  try {
    const rawVal = SpreadsheetApp.getActiveSpreadsheet().getRangeByName('GenEveryDays').getValue();
    if (!isNaN(rawVal) && Number(rawVal) > 0) {
      lookAheadDays = Number(rawVal);
    }
  } catch (e) {
    Logger.log('Config Named Range "GenEveryDays" not found — using default 14 days');
  }

  const today     = new Date(); today.setHours(0, 0, 0, 0);
  const windowEnd = new Date(today); windowEnd.setDate(today.getDate() + lookAheadDays);

  for (let i = 1; i < values.length; i++) {
    const st = values[i][colStatus];
    if (st !== "Processed" && st !== "Pushed to Odoo") continue;

    const eventDate = smartParseDate(values[i][colDate]);
    const flagCell  = sheet.getRange(i + 1, colFlag + 1);

    if (!eventDate) {
      flagCell.setValue("No Date Found");
      continue;
    }
    eventDate.setHours(0, 0, 0, 0);

    if (eventDate >= today && eventDate <= windowEnd) {
      flagCell.setValue("🔔 UPCOMING (" + lookAheadDays + " days)");
    } else if (eventDate < today) {
      flagCell.setValue("📅 Past Event");
    } else {
      flagCell.setValue("⏳ Future (>" + lookAheadDays + " days)");
    }
  }
  safeAlert("Flagging complete!");
}


// ─────────────────────────────────────────────────────────
// SECTION 3: EXPORTERS (Newsletter & Odoo CSV)
// ─────────────────────────────────────────────────────────

function generateWeeklyPulse() {
  const ui    = isHeadless() ? null : SpreadsheetApp.getUi();
  const sheet = SpreadsheetApp.getActiveSpreadsheet().getActiveSheet();
  const values = sheet.getDataRange().getValues();

  if (values.length < 2) {
    safeAlert("No data found. Run the scraper and AI processor first.");
    return;
  }

  const headers = values[0].map(h => h.toString().trim().toLowerCase());
  const col = {
    source:    headers.indexOf("source"),
    url:       headers.indexOf("url"),
    category:  headers.indexOf("ai category"),
    eventDate: headers.indexOf("event date"),
    blog:      headers.indexOf("generated blog draft"),
    status:    headers.indexOf("status"),
    flag:      headers.indexOf("upcoming flag"),
    aiTitle:   headers.indexOf("ai title"),
    qa:        headers.indexOf("qa notes")
  };

  const upcomingEvents = [], newsItems = [];

  for (let i = 1; i < values.length; i++) {
    if (values[i][col.status] !== "Processed") continue;

    // Skip rows with confirmed dead links that couldn't be fixed
    const qaNote = col.qa >= 0 ? (values[i][col.qa] || "").toString().trim() : "";
    if (qaNote === "❌ Dead link") continue;

    const parsedDate    = smartParseDate(values[i][col.eventDate]);
    const formattedDate = parsedDate
      ? Utilities.formatDate(parsedDate, Session.getScriptTimeZone(), "MMMM d, yyyy")
      : (values[i][col.eventDate] || "");

    const item = {
      aiTitle:   sanitizeHTML(values[i][col.aiTitle] || values[i][headers.indexOf("original title")]),
      source:    sanitizeHTML(values[i][col.source]),
      eventDate: sanitizeHTML(formattedDate),
      blog:      sanitizeHTML(values[i][col.blog]),
      url:       values[i][col.url]
        ? values[i][col.url].toString().trim().replace(/"/g, '&quot;')
        : ""
    };

    const flagVal = values[i][col.flag] ? values[i][col.flag].toString() : "";
    if (flagVal.includes("UPCOMING")) {
      upcomingEvents.push(item);
    } else if (values[i][col.category] === "Industry News") {
      newsItems.push(item);
    }
  }

  // Sort both arrays: Newest first (descending by date)
  const sortNewestFirst = (a, b) => {
    const dateA = smartParseDate(a.eventDate);
    const dateB = smartParseDate(b.eventDate);
    if (!dateA && !dateB) return 0;
    if (!dateA) return 1;
    if (!dateB) return -1;
    return dateB.getTime() - dateA.getTime();
  };
  upcomingEvents.sort(sortNewestFirst);
  newsItems.sort(sortNewestFirst);

  const dateLabel = new Date().toLocaleDateString("en-CA", { month: "long", day: "numeric" });

  // High-quality Unsplash image pool for engineering/architecture events
  const images = [
    "https://images.unsplash.com/photo-1497366216548-37526070297c?w=600&h=400&fit=crop",
    "https://images.unsplash.com/photo-1486406146926-c627a92ad1ab?w=600&h=400&fit=crop",
    "https://images.unsplash.com/photo-1581091226825-a6a2a5aee158?w=600&h=400&fit=crop",
    "https://images.unsplash.com/photo-1503387762-592deb58ef4e?w=600&h=400&fit=crop"
  ];

  let html = `
    <!-- Top Hero Section -->
    <section class="s_title pt48 pb48" style="background-color: #f4f6f9; border-bottom: 1px solid #e9ecef;">
      <div class="container text-center">
        <h1 class="display-4" style="color: #1a5276; font-weight: bold;">SPAN-EA NEWSLETTER</h1>
        <p class="lead text-muted mt-2">Curated events and industry updates for ${dateLabel}</p>
      </div>
    </section>
    <!-- Main Content Section -->
    <section class="s_features_grid pt64 pb64 text-left">
      <div class="container">
  `;

  if (upcomingEvents.length > 0) {
    html += `<h2 class="mb-5 pb-2" style="border-bottom: 2px solid #2e86c1; color: #333;">Upcoming Events</h2>`;
    html += `<div class="row">`;
    upcomingEvents.forEach((ev, idx) => {
      const img = images[idx % images.length];
      html += `
        <div class="col-lg-12 mb-5">
          <div class="card shadow-sm border-0 flex-md-row align-items-center h-md-250">
            <div class="col-md-5 p-0 h-100">
              <img src="${img}" class="img-fluid rounded-start w-100" style="object-fit: cover; height: 100%; min-height: 250px;" alt="Event cover image">
            </div>
            <div class="card-body col-md-7 d-flex flex-column align-items-start p-4 p-lg-5">
              <h3 class="mb-2 font-weight-bold" style="color: #1a5276;">${ev.aiTitle}</h3>
              <div class="mb-3 text-muted">
                <i class="fa fa-calendar mr-2" style="color: #2e86c1;"></i> <strong>${ev.eventDate}</strong>
                <span class="mx-2">|</span>
                <i class="fa fa-building mr-2" style="color: #2e86c1;"></i> ${ev.source}
              </div>
              <p class="card-text mb-4 text-justify" style="font-size: 1.05rem; line-height: 1.6;">${ev.blog}</p>
              ${ev.url ? `<a href="${ev.url}" class="btn btn-primary btn-lg rounded-pill px-4">Discover more ➔</a>` : ''}
            </div>
          </div>
        </div>
      `;
    });
    html += `</div>`;
  }

  if (newsItems.length > 0) {
    html += `<h2 class="mt-5 mb-5 pb-2" style="border-bottom: 2px solid #2e86c1; color: #333;">Industry News</h2>`;
    html += `<div class="row pb-5">`;
    newsItems.forEach(ev => {
      html += `
        <div class="col-lg-6 mb-4">
          <div class="card h-100 shadow-sm border-0">
            <div class="card-body p-4">
              <h4 class="mb-2 font-weight-bold" style="color: #1a5276;">${ev.aiTitle}</h4>
              <p class="text-muted small mb-3"><i class="fa fa-newspaper-o mr-1"></i> ${ev.source}</p>
              <p class="card-text mb-3">${ev.blog}</p>
              ${ev.url ? `<a href="${ev.url}" class="text-primary font-weight-bold">Read Full Story ➔</a>` : ''}
            </div>
          </div>
        </div>
      `;
    });
    html += `</div>`;
  }

  if (upcomingEvents.length === 0 && newsItems.length === 0) {
    html += `<p style="color:#888; text-align:center; padding: 40px 0;">No upcoming events or news items found. Run Step 3 (Flag Upcoming Events) first.</p>`;
  }

  html += `
      </div>
    </section>
  `;

  const ss = SpreadsheetApp.getActiveSpreadsheet();
  const draftSheet = ss.getSheetByName("Newsletter Draft") || ss.insertSheet("Newsletter Draft");
  draftSheet.clear().getRange(1, 1).setValue(html);

  const totalItems = upcomingEvents.length + newsItems.length;
  let summaryText = `Included <strong>${totalItems}</strong> item${totalItems !== 1 ? 's' : ''} in the newsletter.`;
  if (upcomingEvents.length > 0 && newsItems.length > 0) {
    summaryText = `Included <strong>${upcomingEvents.length}</strong> Upcoming Event${upcomingEvents.length !== 1 ? 's' : ''} and <strong>${newsItems.length}</strong> News item${newsItems.length !== 1 ? 's' : ''}.`;
  }

  const htmlOut = HtmlService.createHtmlOutput(`
    <div style="font-family: Arial, sans-serif; text-align: center; padding: 20px;">
      <h2 style="color: #2e86c1;">✅ Newsletter Ready</h2>
      <p>${summaryText}</p>
      <a href="data:text/html;charset=utf-8,${encodeURIComponent(html)}"
         download="News.html"
         style="display: inline-block; padding: 12px 24px; background-color: #2e86c1; color: white; text-decoration: none; border-radius: 5px; font-weight: bold; margin-top: 15px;">
        ⬇️ Download News.html (Newsletter)
      </a>
      <p style="font-size: 11px; margin-top: 20px; color: #777;">Save News.html in project folder, then run: python push_to_odoo.py</p>
    </div>
  `).setWidth(400).setHeight(280);

  safeShowDialog(htmlOut, 'SPAN-EA Newsletter Generator');
}

function exportCSVForOdoo() {
  const ui    = isHeadless() ? null : SpreadsheetApp.getUi();
  const sheet = SpreadsheetApp.getActiveSpreadsheet().getActiveSheet();
  const values = sheet.getDataRange().getValues();

  if (values.length < 2) {
    safeAlert("No data found.");
    return;
  }

  const headers = values[0].map(h => h.toString().trim().toLowerCase());
  const col = {
    title:  headers.indexOf("ai title"),
    blog:   headers.indexOf("generated blog draft"),
    url:    headers.indexOf("url"),
    status: headers.indexOf("status"),
    date:   headers.indexOf("event date"),
    flag:   headers.indexOf("upcoming flag"),
    qa:     headers.indexOf("qa notes")
  };

  const csvRows = ['"name","content","website_published","post_date"'];
  let exportCount = 0, skippedPast = 0, skippedDead = 0;

  // Collect exportable rows
  const exportableRows = [];
  values.forEach((row, i) => {
    if (i === 0 || row[col.status] !== "Processed") return;

    // Skip past events
    const flag = (col.flag >= 0 ? row[col.flag].toString() : "").toLowerCase();
    if (flag.includes("past event")) { skippedPast++; return; }

    // Skip confirmed dead links
    const qaNote = col.qa >= 0 ? (row[col.qa] || "").toString().trim() : "";
    if (qaNote === "❌ Dead link") { skippedDead++; return; }

    exportableRows.push(row);
  });

  // Sort by Event Date: Newest first
  exportableRows.sort((a, b) => {
    const dateA = smartParseDate(a[col.date]);
    const dateB = smartParseDate(b[col.date]);
    if (!dateA && !dateB) return 0;
    if (!dateA) return 1;
    if (!dateB) return -1;
    return dateB.getTime() - dateA.getTime();
  });

  exportableRows.forEach(row => {
    let dateStr = "";
    const pDate = smartParseDate(row[col.date]);
    if (pDate) dateStr = Utilities.formatDate(pDate, "GMT", "yyyy-MM-dd HH:mm:ss");

    const sourceUrl = col.url >= 0 ? (row[col.url] || "").toString().trim() : "";
    const content   = `<p>${sanitizeHTML(row[col.blog])}</p>${sourceUrl ? `<p><a href="${sourceUrl}">Source</a></p>` : ''}`;
    csvRows.push(`"${sanitizeHTML(row[col.title]).replace(/"/g, '""')}","${content.replace(/"/g, '""')}","False","${dateStr}"`);
    exportCount++;
  });

  if (exportCount === 0) {
    const extras = [];
    if (skippedPast > 0) extras.push(`${skippedPast} Past Events filtered`);
    if (skippedDead > 0) extras.push(`${skippedDead} Dead Link rows skipped`);
    safeAlert(`No rows to export.${extras.length ? ' (' + extras.join(', ') + ')' : ''}`);
    return;
  }

  const csvString = csvRows.join("\n");

  // Save preview to "Events Export" tab
  const ss = SpreadsheetApp.getActiveSpreadsheet();
  const exportSheet = ss.getSheetByName("Events Export") || ss.insertSheet("Events Export");
  exportSheet.clear();
  exportSheet.getRange(1, 1).setValue("name");
  exportSheet.getRange(1, 2).setValue("content");
  exportSheet.getRange(1, 3).setValue("website_published");
  exportSheet.getRange(1, 4).setValue("post_date");
  exportableRows.forEach((row, idx) => {
    const title = (row[col.title] || "").toString();
    const blog  = (row[col.blog]  || "").toString();
    let dateStr = "";
    const pDate = smartParseDate(row[col.date]);
    if (pDate) dateStr = Utilities.formatDate(pDate, "GMT", "yyyy-MM-dd HH:mm:ss");

    exportSheet.getRange(idx + 2, 1).setValue(title);
    exportSheet.getRange(idx + 2, 2).setValue(blog);
    exportSheet.getRange(idx + 2, 3).setValue("False");
    exportSheet.getRange(idx + 2, 4).setValue(dateStr);
  });

  const skippedMsg = [
    skippedPast > 0 ? `${skippedPast} Past Events` : null,
    skippedDead > 0 ? `${skippedDead} Dead Links` : null
  ].filter(Boolean).join(', ');

  const htmlOut = HtmlService.createHtmlOutput(`
    <div style="font-family: Arial, sans-serif; text-align: center; padding: 20px;">
      <h2 style="color: #2e86c1;">✅ Events Export Ready</h2>
      <p>Exported <strong>${exportCount}</strong> Events${skippedMsg ? `<br><small style="color:#888;">(Filtered: ${skippedMsg})</small>` : ''}.</p>
      <a href="data:text/csv;charset=utf-8,${encodeURIComponent(csvString)}"
         download="Events.csv"
         style="display: inline-block; padding: 12px 24px; background-color: #F05A28; color: white; text-decoration: none; border-radius: 5px; font-weight: bold; margin-top: 15px;">
        ⬇️ Download Events.csv (Blog Posts)
      </a>
      <p style="font-size: 11px; margin-top: 20px; color: #777;">Save Events.csv in project folder, then run: python push_to_odoo.py</p>
    </div>
  `).setWidth(400).setHeight(280);

  safeShowDialog(htmlOut, 'SPAN-EA Events Export');
}


// ─────────────────────────────────────────────────────────
// SECTION 4: HELPERS (Date Parsing, Formatting, API Call)
// ─────────────────────────────────────────────────────────

/**
 * Calls Gemini to categorise, title, date, and draft a blog post for one item.
 */
function callGeminiAPI(title, content, source, manualDate) {
  const apiKey = PropertiesService.getScriptProperties().getProperty(SCRIPT_PROP_KEY);
  if (!apiKey) return { result: null, error: "Missing API Key (Go to Setup > Set API Key)" };

  const srcClean = (source || "").toLowerCase();
  const isEngineering  = srcClean.includes("peo")  || srcClean.includes("ospe");
  const isArchitecture = srcClean.includes("tsa")  || srcClean.includes("oaa");

  let pdHoursName = "Professional Development Credits";
  if (isEngineering)  pdHoursName = "PDH hours (PEO)";
  else if (isArchitecture) pdHoursName = "OAA Structured Learning Hours";

  const currentYear = new Date().getFullYear();

  let readableDate = manualDate;
  if (manualDate) {
    const d = smartParseDate(manualDate);
    if (d) readableDate = Utilities.formatDate(d, Session.getScriptTimeZone(), "MMMM d, yyyy");
  }
  const dateInstruction = readableDate
    ? `\nEvent Date provided by QA: ${readableDate}. CRITICAL INSTRUCTION: You MUST return exactly "${readableDate}" for eventDate, and weave this date into the blogDraft naturally.`
    : "";

  const prompt = `Role: You are SPAN-EA's blog editor. SPAN-EA is a professional community that curates and recommends industry events and news for newcomer engineers and architects settling in Ontario, Canada.
IMPORTANT: SPAN-EA does NOT organize these events. It discovers them from TSA, OAA, PEO, and OSPE and recommends them to its members.

Voice & Style:
- Write in SPAN-EA's warm, encouraging, professional tone — as if a mentor is recommending something valuable to a newcomer colleague.
- DO NOT just summarize the original content. REPHRASE and REWRITE it in SPAN-EA's own editorial voice.
- Use phrases like "This is a great opportunity for...", "If you're looking to...", "Don't miss...", "Worth checking out for anyone interested in...".
- The output should feel like an original SPAN-EA blog post, NOT a copy-paste or summary of the source.

Context: Today is ${new Date().toDateString()}. Current year is ${currentYear}. Assume year ${currentYear} for any date without a specified year.
Source: ${source || "Unknown"}
Relevant credential: ${pdHoursName}${dateInstruction}

Task: Analyze the article below. Return a JSON object with exactly these fields:
1. "category": "Upcoming Event" OR "Industry News"
2. "eventDate": A date string like "March 15, 2026". CRITICAL: DO NOT confuse "(News Published: YYYY-MM-DD)" with the event date. Only extract the true event date from the content. If none found, return "Date TBD".
3. "aiTitle": A catchy, professional blog title (max 10 words). Use curiosity-gap or benefit-driven phrasing. Do NOT copy the original title.
4. "cpdInfo": CRITICAL: ONLY extract professional credits (e.g., ${pdHoursName}) if the source explicitly mentions them. If not found, return exactly "Not specified". NEVER guess or assume.
5. "blogDraft": A publish-ready blog post (4-5 sentences) in SPAN-EA's editorial voice:
   - Sentence 1: Hook — what is this, who runs it, and when.
   - Sentence 2: Why newcomer engineers/architects in Ontario should care (career growth, networking, skill building).
   - Sentence 3: Key takeaways or what attendees will gain. IF AND ONLY IF the source mentions ${pdHoursName}, state it here. If NOT mentioned, DO NOT mention credits at all.
   - Sentence 4: Practical details (cost, format, deadline).
   - Sentence 5: Call-to-action — visit the link, register, or RSVP.
   NEVER say "SPAN-EA is hosting" — always frame as a recommendation.

Title: "${title}"
Content: "${content.toString().substring(0, 1200)}"

Respond ONLY with valid JSON. No markdown, no explanation, no extra text.`;

  try {
    const url = `https://generativelanguage.googleapis.com/v1beta/models/${AI_MODEL_NAME}:generateContent?key=${apiKey}`;
    const options = {
      method: "post",
      contentType: "application/json",
      payload: JSON.stringify({
        contents: [{ parts: [{ text: prompt }] }],
        generationConfig: { temperature: 0.6, maxOutputTokens: 1024 }
      }),
      muteHttpExceptions: true
    };

    const resp = UrlFetchApp.fetch(url, options);
    const code = resp.getResponseCode();
    if (code !== 200) {
      return { result: null, error: "HTTP " + code + " — check your API key and billing/quota" };
    }

    const text = JSON.parse(resp.getContentText()).candidates[0].content.parts[0].text.trim();
    const match = text.match(/\{[\s\S]*\}/);
    if (match) {
      const result = JSON.parse(match[0]);
      if (result.category && result.eventDate && result.blogDraft) {
        return { result: result, error: null };
      }
    }
    return { result: null, error: "Invalid AI output format — JSON fields missing" };
  } catch (e) {
    return { result: null, error: e.toString() };
  }
}

/**
 * Smart Date Parser: Cleans messy date strings from websites (no API tokens used).
 */
function smartParseDate(rawString) {
  if (!rawString || rawString.toString().trim() === "") return null;
  if (rawString instanceof Date) return rawString;

  let str = rawString.toString().trim();

  // Remove ordinal suffixes: 1st, 2nd, 3rd, 4th …
  str = str.replace(/(\d+)(st|nd|rd|th)/gi, "$1");

  // Remove day names: Monday, Tue, etc.
  str = str.replace(/(?:Monday|Tuesday|Wednesday|Thursday|Friday|Saturday|Sunday|Mon|Tue|Wed|Thu|Fri|Sat|Sun),?\s*/gi, "");

  let date = new Date(str);

  // If invalid but looks like "May 10" (no year), append current year
  if (isNaN(date.getTime())) {
    date = new Date(str + ", " + new Date().getFullYear());
  }

  return isNaN(date.getTime()) ? null : date;
}

function applyDatePicker() {
  const ui    = isHeadless() ? null : SpreadsheetApp.getUi();
  const sheet = SpreadsheetApp.getActiveSpreadsheet().getActiveSheet();
  const headers = sheet.getRange(1, 1, 1, sheet.getLastColumn()).getValues()[0];
  const colIdx  = headers.findIndex(h => h.toString().trim().toLowerCase() === "event date");
  if (colIdx === -1) {
    safeAlert("Could not find 'Event Date' column.");
    return;
  }
  const range = sheet.getRange(2, colIdx + 1, sheet.getMaxRows() - 1, 1);
  range.setDataValidation(
    SpreadsheetApp.newDataValidation()
      .requireDate()
      .setAllowInvalid(false)
      .setHelpText("Please enter a valid date or double-click to pick from the calendar.")
      .build()
  );
  range.setNumberFormat("MMMM d, yyyy");
  safeAlert("Date Picker applied to Column " + columnToLetter(colIdx + 1));
}

/**
 * QA DROPDOWN: Applies a dropdown to the "QA Notes" column.
 */
function applyQADropdown() {
  const ui    = isHeadless() ? null : SpreadsheetApp.getUi();
  const sheet = SpreadsheetApp.getActiveSpreadsheet().getActiveSheet();
  const headers = sheet.getRange(1, 1, 1, sheet.getLastColumn()).getValues()[0];
  const colIdx  = headers.findIndex(h => h.toString().trim().toLowerCase() === "qa notes");
  if (colIdx === -1) {
    safeAlert("Could not find 'QA Notes' column.");
    return;
  }
  const range = sheet.getRange(2, colIdx + 1, sheet.getMaxRows() - 1, 1);
  range.setDataValidation(
    SpreadsheetApp.newDataValidation()
      .requireValueInList(["✅ Approved", "❌ Not an event", "❌ Past event", "❌ Dead link"], true)
      .setAllowInvalid(true)
      .setHelpText("Select a QA status or type your own note.")
      .build()
  );
  safeAlert("QA Dropdown applied to Column " + columnToLetter(colIdx + 1) + " (QA Notes)");
}

function setGeminiApiKey() {
  const ui = isHeadless() ? null : SpreadsheetApp.getUi();
  const response = ui.prompt('Set API Key', 'Paste your Gemini API Key:', ui.ButtonSet.OK_CANCEL);
  if (response.getSelectedButton() === ui.Button.OK) {
    const key = response.getResponseText().trim();
    if (key) {
      PropertiesService.getScriptProperties().setProperty(SCRIPT_PROP_KEY, key);
      safeAlert("✅ Key saved successfully!");
    } else {
      safeAlert("No key entered.");
    }
  }
}

function debugGeminiAPI() {
  const ui     = SpreadsheetApp.getUi();
  const apiKey = PropertiesService.getScriptProperties().getProperty(SCRIPT_PROP_KEY);
  if (!apiKey) {
    safeAlert("No API key found.\nGo to: Setup > Set Gemini API Key");
    return;
  }
  safeAlert("Key found (first 8 chars): " + apiKey.substring(0, 8) + "...\nCalling Gemini now...");
  const url = `https://generativelanguage.googleapis.com/v1beta/models/${AI_MODEL_NAME}:generateContent?key=${apiKey}`;
  try {
    const resp = UrlFetchApp.fetch(url, {
      method: "post",
      contentType: "application/json",
      payload: JSON.stringify({ contents: [{ parts: [{ text: "Respond: OK" }] }] }),
      muteHttpExceptions: true
    });
    safeAlert("HTTP " + resp.getResponseCode() + "\n\n" + resp.getContentText().substring(0, 500));
  } catch (err) {
    safeAlert("Exception: " + err.toString());
  }
}

function columnToLetter(column) {
  let temp, letter = '';
  while (column > 0) {
    temp   = (column - 1) % 26;
    letter = String.fromCharCode(65 + temp) + letter;
    column = (column - temp - 1) / 26;
  }
  return letter;
}

function sanitizeHTML(str) {
  if (!str) return "";
  return str.toString()
    .replace(/&/g,  '&amp;')
    .replace(/</g,  '&lt;')
    .replace(/>/g,  '&gt;')
    .replace(/"/g,  '&quot;');
}


// ─────────────────────────────────────────────────────────
// SECTION 4B: URL VALIDATOR (Dead Link Detector + AI Fixer)
// ─────────────────────────────────────────────────────────

/**
 * isUrlAlive: Makes a real HTTP request to verify the URL is reachable.
 * Returns true if alive (HTTP 200–399), false otherwise.
 */
function isUrlAlive(url) {
  if (!url || url.trim() === "") return false;
  try {
    const resp = UrlFetchApp.fetch(url.trim(), {
      method: "get",
      muteHttpExceptions: true,
      followRedirects: true,
      headers: { "User-Agent": "Mozilla/5.0 (compatible; SPAN-EA-Bot/1.0)" }
    });
    const code = resp.getResponseCode();
    return (code >= 200 && code < 400);
  } catch (e) {
    Logger.log("isUrlAlive error for " + url + ": " + e.toString());
    return false;
  }
}

/**
 * findWorkingUrlWithGemini: If a URL is dead, asks Gemini to suggest
 * a working replacement based on the event title, source, and content snippet.
 * Verifies the suggestion is actually alive before returning it.
 * Falls back to the original URL if no working alternative is found.
 */
function findWorkingUrlWithGemini(title, content, source, deadUrl) {
  const apiKey = PropertiesService.getScriptProperties().getProperty(SCRIPT_PROP_KEY);
  if (!apiKey) return deadUrl;

  const prompt = `You are a web research assistant. The following URL is dead or broken:
URL: ${deadUrl}
Event/Article Title: "${title}"
Source Organization: "${source}"
Content snippet: "${(content || "").toString().substring(0, 400)}"

Your task: Find and return a WORKING replacement URL for this event or article.

Rules:
1. Look for the event on the source organization's official website (${source}).
2. Try https instead of http, or check /events or /news pages.
3. Only return a URL you are highly confident leads to working content about THIS specific event.
4. If you cannot find a working alternative, return the original URL unchanged.

Respond ONLY with valid JSON, no markdown:
{"workingUrl": "https://...", "confidence": "high|medium|low", "reason": "brief explanation"}`;

  try {
    const url  = `https://generativelanguage.googleapis.com/v1beta/models/${AI_MODEL_NAME}:generateContent?key=${apiKey}`;
    const resp = UrlFetchApp.fetch(url, {
      method: "post",
      contentType: "application/json",
      payload: JSON.stringify({
        contents: [{ parts: [{ text: prompt }] }],
        generationConfig: { temperature: 0.2, maxOutputTokens: 256 }
      }),
      muteHttpExceptions: true
    });

    if (resp.getResponseCode() !== 200) return deadUrl;

    const text  = JSON.parse(resp.getContentText()).candidates[0].content.parts[0].text.trim();
    const match = text.match(/\{[\s\S]*\}/);
    if (match) {
      const parsed    = JSON.parse(match[0]);
      const suggested = (parsed.workingUrl || "").trim();
      if (suggested && suggested !== deadUrl) {
        if (isUrlAlive(suggested)) {
          Logger.log("✅ AI fixed URL: " + suggested + " (was: " + deadUrl + ")");
          return suggested;
        }
      }
    }
  } catch (e) {
    Logger.log("findWorkingUrlWithGemini error: " + e.toString());
  }
  return deadUrl;
}

/**
 * checkAndFixUrl: Master URL validator.
 * 1. Checks if the URL is alive.
 * 2. If dead, asks Gemini to find a working replacement.
 * 3. Returns { url, wasFixed, isAlive }.
 */
function checkAndFixUrl(url, title, content, source) {
  if (!url || url.trim() === "") {
    return { url: "", wasFixed: false, isAlive: false };
  }

  if (isUrlAlive(url)) {
    return { url: url, wasFixed: false, isAlive: true };
  }

  // URL is dead — attempt AI-assisted fix
  Logger.log("🔴 Dead link detected: " + url);
  const fixedUrl   = findWorkingUrlWithGemini(title, content, source, url);
  const wasFixed   = fixedUrl !== url;
  const fixedAlive = wasFixed ? isUrlAlive(fixedUrl) : false;

  return { url: fixedUrl, wasFixed: wasFixed, isAlive: fixedAlive };
}


// ─────────────────────────────────────────────────────────
// SECTION 5: DIRECT ODOO PUSH (Phase 2 Beta - JSON-RPC)
// ─────────────────────────────────────────────────────────

/**
 * Store Odoo credentials in Script Properties.
 * Run once from: SPAN-EA AI > Setup > Set Odoo Credentials
 */
function setOdooCredentials() {
  const ui    = isHeadless() ? null : SpreadsheetApp.getUi();
  const props = PropertiesService.getScriptProperties();

  const urlResp = ui.prompt('Odoo Setup (1/4)', 'Enter Odoo URL (e.g., https://span-ea-ai.odoo.com):', ui.ButtonSet.OK_CANCEL);
  if (urlResp.getSelectedButton()  !== ui.Button.OK) return;

  const dbResp  = ui.prompt('Odoo Setup (2/4)', 'Enter Database name (e.g., span-ea-ai):', ui.ButtonSet.OK_CANCEL);
  if (dbResp.getSelectedButton()   !== ui.Button.OK) return;

  const userResp = ui.prompt('Odoo Setup (3/4)', 'Enter Odoo login email:', ui.ButtonSet.OK_CANCEL);
  if (userResp.getSelectedButton() !== ui.Button.OK) return;

  const passResp = ui.prompt('Odoo Setup (4/4)', 'Enter Odoo password or API key:', ui.ButtonSet.OK_CANCEL);
  if (passResp.getSelectedButton() !== ui.Button.OK) return;

  props.setProperty('ODOO_URL',      urlResp.getResponseText().trim().replace(/\/$/, ''));
  props.setProperty('ODOO_DB',       dbResp.getResponseText().trim());
  props.setProperty('ODOO_USER',     userResp.getResponseText().trim());
  props.setProperty('ODOO_PASSWORD', passResp.getResponseText().trim());

  safeAlert('✅ Odoo credentials saved!\n\nYou can now use: Step 6: Push Directly to Odoo');
}

/**
 * JSON-RPC helper: calls Odoo's /jsonrpc endpoint.
 */
function odooJsonRpc_(url, service, method, args) {
  const payload = {
    jsonrpc: "2.0",
    method:  "call",
    id:      new Date().getTime(),
    params:  { service: service, method: method, args: args }
  };

  const resp = UrlFetchApp.fetch(url + "/jsonrpc", {
    method:      "post",
    contentType: "application/json",
    payload:     JSON.stringify(payload),
    muteHttpExceptions: true
  });

  const result = JSON.parse(resp.getContentText());
  if (result.error) {
    throw new Error(result.error.data ? result.error.data.message : result.error.message);
  }
  return result.result;
}

/**
 * Push processed blog posts directly to Odoo as unpublished drafts via JSON-RPC.
 * Skips rows with confirmed dead links.
 */
function pushToOdooDirectly() {
  const ui        = SpreadsheetApp.getUi();
  const startTime = Date.now();

  // Ask before overwriting the Newsletter page
  const nlResponse = safeAlert(
    'Update Newsletter Page? ⚠️',
    'Do you also want to overwrite the Odoo Newsletter page?\n\n⚠️ WARNING: This will DESTROY any manual edits you made in Odoo.\n\nClick "No" to push only Blog posts and keep your Newsletter edits safe.',
    ui.ButtonSet.YES_NO
  );

  // 1. Load credentials
  const props   = PropertiesService.getScriptProperties();
  const odooUrl = props.getProperty('ODOO_URL');
  const odooDB  = props.getProperty('ODOO_DB');
  const odooUser = props.getProperty('ODOO_USER');
  const odooPass = props.getProperty('ODOO_PASSWORD');

  if (!odooUrl || !odooDB || !odooUser || !odooPass) {
    safeAlert('❌ Odoo credentials not set!\n\nGo to: SPAN-EA AI > Setup > Set Odoo Credentials');
    return;
  }

  // 2. Authenticate
  safeAlert('🔄 Connecting to Odoo...\n\nURL: ' + odooUrl + '\nDB: ' + odooDB);
  let uid;
  try {
    uid = odooJsonRpc_(odooUrl, "common", "login", [odooDB, odooUser, odooPass]);
    if (!uid) {
      safeAlert('❌ Authentication failed!\nCheck credentials in Setup > Set Odoo Credentials.');
      return;
    }
  } catch (e) {
    safeAlert('❌ Cannot connect to Odoo:\n' + e.toString() + '\n\nFallback: Use python push_to_odoo.py instead.');
    return;
  }

  // 3. Find or create the blog
  let blogId;
  try {
    const blogs = odooJsonRpc_(odooUrl, "object", "execute_kw",
      [odooDB, uid, odooPass, "blog.blog", "search_read", [[]], { "fields": ["id", "name"], "limit": 1 }]
    );
    blogId = blogs.length > 0 ? blogs[0].id : null;
    if (!blogId) {
      blogId = odooJsonRpc_(odooUrl, "object", "execute_kw",
        [odooDB, uid, odooPass, "blog.blog", "create", [{ "name": "Our blog" }]]
      );
    }
  } catch (e) {
    safeAlert('❌ Cannot find/create blog:\n' + e.toString());
    return;
  }

  // 4. Load existing post titles for duplicate check
  const existingTitles = new Set();
  try {
    const existingPosts = odooJsonRpc_(odooUrl, "object", "execute_kw",
      [odooDB, uid, odooPass, "blog.post", "search_read", [[]], { "fields": ["name"], "limit": 500 }]
    );
    existingPosts.forEach(p => existingTitles.add(p.name.trim().toLowerCase()));
  } catch (e) {
    Logger.log("Could not fetch existing posts: " + e.toString());
  }

  // 5. Read sheet
  const sheet  = SpreadsheetApp.getActiveSpreadsheet().getActiveSheet();
  const values = sheet.getDataRange().getValues();
  const headers = values[0].map(h => h.toString().trim().toLowerCase());

  const col = {
    status:  headers.indexOf("status"),
    aiTitle: headers.indexOf("ai title"),
    blog:    headers.indexOf("generated blog draft"),
    url:     headers.indexOf("url"),
    date:    headers.indexOf("event date"),
    flag:    headers.indexOf("upcoming flag"),
    qa:      headers.indexOf("qa notes")
  };

  // 6. Collect rows eligible for push
  let created = 0, skipped = 0, failed = 0;

  const pushableRows = [];
  for (let i = 1; i < values.length; i++) {
    const status = (values[i][col.status] || "").toString().trim();
    if (status !== "Processed") continue;

    // Skip past events
    const flag = col.flag >= 0 ? (values[i][col.flag] || "").toString().toLowerCase() : "";
    if (flag.includes("past event")) continue;

    // Skip confirmed dead links
    const qaNote = col.qa >= 0 ? (values[i][col.qa] || "").toString().trim() : "";
    if (qaNote === "❌ Dead link") continue;

    pushableRows.push({ rowIndex: i, rowData: values[i] });
  }

  // Sort: Furthest future first → gets lowest blog ID → appears at bottom; soonest gets top
  pushableRows.sort((a, b) => {
    const dateA = smartParseDate(a.rowData[col.date]);
    const dateB = smartParseDate(b.rowData[col.date]);
    if (!dateA && !dateB) return 0;
    if (!dateA) return -1;
    if (!dateB) return 1;
    return dateB.getTime() - dateA.getTime();
  });

  // 7. Push each row to Odoo
  for (let idx = 0; idx < pushableRows.length; idx++) {
    const r   = pushableRows[idx];
    const i   = r.rowIndex;
    const row = r.rowData;

    if (Date.now() - startTime > 300000) {
      safeAlert('⏱️ Time limit approaching! Pushed ' + created + ' posts so far.\nRun Step 6 again to continue.');
      break;
    }

    const title     = (row[col.aiTitle] || "").toString().trim();
    const blogDraft = (values[i][col.blog] || "").toString().trim();
    const sourceUrl = col.url >= 0 ? (values[i][col.url] || "").toString().trim() : "";

    if (!title || !blogDraft) continue;
    if (existingTitles.has(title.toLowerCase())) { skipped++; continue; }

    const content = '<p>' + blogDraft + '</p>' +
      (sourceUrl ? '<p><a href="' + sourceUrl + '">Source</a></p>' : '');

    const eventDate = col.date >= 0 ? smartParseDate(values[i][col.date]) : null;
    const postData  = {
      "blog_id":           blogId,
      "name":              title,
      "content":           content,
      "website_published": false
    };
    if (eventDate) {
      postData["post_date"] = Utilities.formatDate(eventDate, "GMT", "yyyy-MM-dd HH:mm:ss");
    }

    try {
      odooJsonRpc_(odooUrl, "object", "execute_kw",
        [odooDB, uid, odooPass, "blog.post", "create", [postData]]
      );
      sheet.getRange(i + 1, col.status + 1).setValue("Pushed to Odoo");
      existingTitles.add(title.toLowerCase());
      created++;
      Utilities.sleep(1000);
    } catch (e) {
      // Retry without post_date (some Odoo versions reject it via external API)
      if (postData["post_date"]) {
        Logger.log('Retrying without post_date: ' + title);
        try {
          delete postData["post_date"];
          odooJsonRpc_(odooUrl, "object", "execute_kw",
            [odooDB, uid, odooPass, "blog.post", "create", [postData]]
          );
          sheet.getRange(i + 1, col.status + 1).setValue("Pushed to Odoo");
          existingTitles.add(title.toLowerCase());
          created++;
          Utilities.sleep(1000);
        } catch (e2) {
          Logger.log('Failed to push (retry): ' + title + ' — ' + e2.toString());
          failed++;
        }
      } else {
        Logger.log('Failed to push: ' + title + ' — ' + e.toString());
        failed++;
      }
    }
  }

  // 8. Optionally push Newsletter HTML to Odoo page
  let newsletterStatus = "⏭️ Skipped (no Newsletter Draft tab)";
  const nlSheet = SpreadsheetApp.getActiveSpreadsheet().getSheetByName("Newsletter Draft");

  if (nlResponse === ui.Button.NO) {
    newsletterStatus = "🛡️ Skipped (protected your manual edits)";
  } else if (nlSheet) {
    const nlHtml = nlSheet.getRange(1, 1).getValue().toString().trim();
    if (nlHtml) {
      try {
        const pages = odooJsonRpc_(odooUrl, "object", "execute_kw",
          [odooDB, uid, odooPass, "website.page", "search_read",
           [[["url", "like", "newsletter"]]],
           { "fields": ["id", "name", "url", "view_id"], "limit": 1 }]
        );
        if (pages.length > 0) {
          const page   = pages[0];
          const viewId = Array.isArray(page.view_id) ? page.view_id[0] : page.view_id;
          const newArch = '<t t-name="website.newsletter_page"><t t-call="website.layout">' +
            '<div id="wrap" class="oe_structure oe_empty">' +
            '<section class="s_text_block pt32 pb32"><div class="container">' +
            nlHtml + '</div></section></div></t></t>';
          odooJsonRpc_(odooUrl, "object", "execute_kw",
            [odooDB, uid, odooPass, "ir.ui.view", "write",
             [[viewId], { "arch_db": newArch }]]
          );
          newsletterStatus = "✅ Updated: " + page.url;
        } else {
          newsletterStatus = "⚠️ No newsletter page found in Odoo";
        }
      } catch (e) {
        Logger.log("Newsletter push error: " + e.toString());
        newsletterStatus = "⚠️ Failed (use python push_to_odoo.py --newsletter-only)";
      }
    } else {
      newsletterStatus = "⏭️ Skipped (Newsletter Draft tab is empty)";
    }
  }

  // 9. Show results dialog
  const duration = ((Date.now() - startTime) / 1000).toFixed(1);
  const htmlOut  = HtmlService.createHtmlOutput(`
    <div style="font-family: Arial, sans-serif; text-align: center; padding: 20px;">
      <h2 style="color: #2e86c1;">⚡ Direct Odoo Push Complete</h2>
      <p style="font-size: 16px; text-align: left; margin: 15px 0;">
        <strong>📝 Blog Posts:</strong><br>
        &nbsp;&nbsp;✅ Created: <strong>${created}</strong> drafts<br>
        &nbsp;&nbsp;⏭️ Skipped: <strong>${skipped}</strong> (duplicates)<br>
        ${failed > 0 ? '&nbsp;&nbsp;❌ Failed: <strong>' + failed + '</strong><br>' : ''}
        <br>
        <strong>📰 Newsletter:</strong><br>
        &nbsp;&nbsp;${newsletterStatus}<br>
        <br>
        ⏱️ Time: <strong>${duration}s</strong>
      </p>
      <p style="margin-top: 10px;">
        <a href="${odooUrl}/odoo/website" target="_blank"
           style="display: inline-block; padding: 12px 24px; background-color: #2e86c1; color: white; text-decoration: none; border-radius: 5px; font-weight: bold;">
          🌐 Open Odoo to Review
        </a>
      </p>
      <p style="font-size: 11px; margin-top: 10px; color: #777;">Blog posts created as unpublished drafts. Newsletter page updated directly.</p>
    </div>
  `).setWidth(420).setHeight(400);

  safeShowDialog(htmlOut, 'SPAN-EA Direct Push (Phase 2 Beta)');
}


// ─────────────────────────────────────────────────────────
// SECTION 7: ADMIN TOOLS
// ─────────────────────────────────────────────────────────

/**
 * Resets any "Pushed to Odoo" status back to "Processed".
 * Useful for re-pushing events after testing or fixing issues.
 */
function resetPushedToProcessed() {
  const sheet  = SpreadsheetApp.getActiveSpreadsheet().getActiveSheet();
  const values = sheet.getDataRange().getValues();

  if (values.length <= 1) return;

  const statusColIndex = values[0].findIndex(h => h.toString().trim().toLowerCase() === "status");
  if (statusColIndex === -1) {
    safeAlert("❌ Could not find 'Status' column.");
    return;
  }

  let count = 0;
  for (let i = 1; i < values.length; i++) {
    const currentStatus = (values[i][statusColIndex] || "").toString().trim();
    if (currentStatus === "Pushed to Odoo") {
      sheet.getRange(i + 1, statusColIndex + 1).setValue("Processed");
      count++;
    }
  }

  safeAlert(
    count > 0
      ? `✅ Reset ${count} row(s) back to "Processed" — ready to re-push.`
      : `⚠️ No rows with "Pushed to Odoo" status were found.`
  );
} 