# BioSpine v5 - what was done for each item in UPGRADES_for_website.pdf

| # | Request in the PDF | What you now have | Where |
|---|---|---|---|
| 1 | Review system, once after the 5th use | A pop-up appears **once**, right after the 5th saved session (stars + optional name + comment). "Maybe later" counts too, so nobody is asked twice. | `extras.js` (review), `views.py` (`api_review`, `api_review_dismiss`), model `Review` |
| 2 | Light / dark mode | Toggle on the home page, in the sidebar and in the top bar. Remembers the choice; first visit follows the phone / PC setting. | `theme.js`, `style.css` (variables), `extras.css` |
| 3 | Access each person's data + large-scale analysis | `/staff/analytics/` already had per-user pages and platform charts; now each person has **Excel + PDF report** buttons, and the dashboard has an **all-users report**. | `views_analytics.py`, `analytics.py`, `reports.py` |
| 4 | Hourly back breaks, usable in meetings | **Back Break** page: remind every 30 / 45 / 60 / 90 / 120 min, **Meeting-friendly mode** (silent, small corner note, "remind me in 15 min"), four 1-minute guided stretches. Works even without the device. | `extras.js` |
| 5 | Remove AI assistant if not working | One switch: `AI_ENABLED=False` removes the AI Physio, AI check-up, Chats tab and every AI sentence on the home page. It is also hidden automatically when `GEMINI_API_KEY` is empty. | `settings.py`, `context.py`, `index.html` |
| 6 | Simpler, more detailed client reports | **My report** on the Session History page: plain-language findings (best day, best hour, most common slouch, trend vs the previous period) with PDF and Excel download. The old detailed clinical PDF per session is still there. | `extras.js` |
| 7 | Documented report on the admin side | Per person (Excel / PDF) and for all users (Excel / PDF) with **week-by-week averages**, every user's totals, compliance spread and the reviews. | `reports.py`, `views_analytics.py` |
| 8 | Biomechanics & RULA page interactive | Renamed **Posture Lab**: Neck Load slider with animated figure, Desk Risk Check (RULA-style), 5-question Quiz, and a Science tab. | `index.html`, `extras.js` |
| 9 | Session history .json -> Excel | **Download Excel** button (sheets: Summary, Sessions, Day by day, Slouch types, Activity log). JSON stays only as a "Backup file". | `extras.js` |
| 10 | Device & telemetry graphics more organized | **My Device** page: status banner, 3 numbered steps (Connect, Set good posture, Check it works) and live gauges + signal quality. | `index.html`, `extras.js` |
| 11 | More interactive home page, photos, admin-chosen reviews | New home page: playable neck-load demo, auto-sliding slides, flip cards, photo gallery, animated counters, FAQ and a **reviews carousel that only shows reviews you approve** (tick "Show on home page" in `/staff/analytics/reviews/` or in `/admin/`). | `index.html`, `extras.css`, `extras.js` |
| 12 | Friendly language | Renamed e.g. "Zero Baseline" -> "Set my good posture", "Sagittal" -> "Forward lean", "Telemetry" -> "Live sensor readings", "Haptic" -> "Vibration". | all screens |
| 13 | Emails really sent, commands working | The sign-up message now tells the truth (it used to say "we sent an email" even when it failed). Gmail port 465/587 handled, a proper default From address, and `python manage.py check_email you@example.com` prints the real error. Fixed broken `</o>` tags in the page. | `emails.py`, `settings.py`, `check_email` command |
| 14 | Feel like a game | XP, 10 levels with titles, daily quests, 15 badges, flame streak, confetti on level-up / badge, XP strip on the dashboard. | `extras.js`, `extras.css` |

## Honest notes
* The "photos" are **illustrations I generated** (`static/img/gallery/`). To use real photos, put your files there with the same names (or edit the `<img>` lines in `templates/index.html`).
* Reviews are empty at first - nothing is invented. They appear only after clients write one and you approve it.
* Excel download uses the SheetJS library from cdnjs. If it cannot load, the button saves a CSV file that opens in Excel.
* New packages: `openpyxl`, `reportlab` (already added to `requirements.txt`). Run `pip install -r requirements.txt` and `python manage.py migrate` (new migration `0003_v5_reviews`).

---
# v5.1 - second round (admin side, body measurements, 3D background)

| Request | What you now have | Where |
|---|---|---|
| Staff analytics: most detailed, split into tabs | `/staff/analytics/` now has 8 tabs, one page each: **Overview, Users, Engagement, Posture quality, Time patterns, Body & BMI, Reviews, Reports**. Light/dark switch included. | `views_analytics.py`, `analytics2.py`, `templates/analytics/*.html`, `static/staff.js` |
| A tab with a list of user profiles | **Users** tab: a card per person (status, sessions, wear time, compliance, average lean, mini trend line, streak, BMI). Search, filter by status or BMI, sort, cards/table view, pages of 24. | `users.html` |
| Click a profile to see what the user sees | The profile page has 7 sub-tabs: **Report** (the same plain-language "My report" the user sees, 7/30/90 days/all), **Day by day** (time spent each day, avg deviation, compliance, alerts, first/last time), **Time slots** (average deviation in every hour, 5 parts of the day, weekdays, heat-map), **Sessions** (every session), **Weekly trend**, **Profile & settings** (account, height/weight/BMI, thresholds), **Activity** (timeline and AI chats if AI is on). Excel/PDF buttons stay on top. | `user_detail.html`, `analytics2.user_profile_context` |
| Make analytics more efficient | **Engagement**: funnel (signed up → confirmed email → first session → 5 → 20 sessions → 7-day streak), stickiness, return rate, weekly retention. **Posture quality**: daily compliance and deviation trend, spreads, who is improving or slipping. **Time patterns**: busiest/weakest hours, weekday and hour heat-map. **Body & BMI**: BMI groups against posture. Overview now only keeps the key numbers and people to look at. | those templates |
| Ask height and weight of new users and calculate it | The sign-up form asks for **height (cm) and weight (kg)** and shows the **BMI live**. Settings has a new **My body** card (BMI, category, healthy-weight range, scale). Saved on the account; shown to you in the admin (cards, profile page, Excel/PDF/CSV). Older accounts can add it in Settings. | `index.html`, `extras.js`, `body.py`, migration `0004_v51_body_metrics` |
| 3D moving background for the log-in page | A slowly turning 3D double-helix with drifting particles that follows the mouse (no extra library, pauses when the page is hidden, respects "reduce motion"). | `extras.js` (`initBg3D`), `extras.css` |

Notes
* BMI uses the standard adult bands (under 18.5, 18.5-24.9, 25-29.9, 30+). It is a rough guide, not a diagnosis, and the privacy page now mentions that height and weight are stored.
* Height and weight are required on the sign-up form but optional in the API/database, so old accounts keep working.
* The server stores only a **summary per session** (duration, score, alerts, average lean). The time-slot analysis therefore splits each session across the clock hours it covered; second-by-second data stays on the user's device.
* After unzipping run `python manage.py migrate` (new migration 0004).

---
# v5.5 - data to the staff side, directions, alarm sound, level on every device

| Problem reported | Cause found | Fix |
|---|---|---|
| Staff Excel had no posture data, no time, no graphs | The app only sent 4 numbers per session (no start time, no graph), demo sessions are practice only and were never sent, and a failed upload was silently lost | Each real-device session now sends its start / end time, lean-angle graph, alert log, slouch types and settings. Failed uploads are kept and retried automatically (safe to repeat, no duplicates). Settings → **Test mode** also sends demo sessions, so you can test the staff pages without a sensor. |
| Staff want the time and graph of each time period | Not stored before | Staff profile → **Sessions** tab: every time period as a card with its time range, lean graph (with the alert angle and slouching periods) and a circle diagram. Each opens a full page with the event log. **Day by day** now lists the time periods used each day. |
| Graphs and circle diagrams in the user report | - | The per-user **PDF** and **Excel** reports now contain a circle diagram of good posture vs slouching, a sheet per recent session with its graph and circle diagram, and a "Time periods by day" sheet. |
| Forward shown as left, left as forward, back as right, right as back | In the sensor code the forward axis and the sideways axis were swapped (chip turned 90 degrees on the neck), so the buzz thresholds were also applied to the wrong direction | Fixed in `firmware/BioSpine_ESP32/BioSpine_ESP32.ino` (**needs re-flashing**; saved good-posture values are cleared once, so press "Set my good posture" again). For sensors that cannot be re-flashed yet: Settings → **Fix directions**. |
| No sound alarm | The old chime was off by default and very quiet | `static/audio/alarm.mp3` (your sound, trimmed to 3.4 s) plays when a slouch is detected and repeats until you sit up. On by default, with volume, repeat and **Test the alarm**. Always silent in Meeting Mode. |
| Level reset to zero on another device | XP was worked out from sessions stored only on that device; badges, back breaks and quizzes lived only in that browser | XP and badge totals now come from the account on the server, and back-break / quiz / quest / badge progress is saved on the account and merged on login, so the level follows you. |

After unzipping run `python manage.py migrate` (new migration 0005). Re-flash the sensor with the new `.ino`.

---
# v5.6 - buzzer removed, review any time, fixed sidebar

* **Buzzer removed from the website.** The "Vibration on the sensor" switch, the "Test the vibration" button and the vibration status are gone, and all wording now talks about the alarm sound and the on-screen reminder. The website now always tells the sensor to keep its motor off (`buzzer` is forced to false in `static/app.js`). The sensor code itself still contains the motor routine; to bring buzzing back, remove the `userSettings.buzzer = false;` line in `sanitizeSettings()`.
* **Review any time.** **⭐ Write a review** at the bottom of the sidebar (and in Settings → Account, for phones). It opens the review box; people who already reviewed see their old rating and comment and can change it. An edited review goes back to you for approval before it can show on the home page.
* **Fixed sidebar.** The sidebar no longer moves when the page scrolls. The bottom block (Write a review, Light/Dark, Performance, Sign Out, links) is always on screen; on a short window only the page list in the middle scrolls.

---
# v5.7 - the new BioSpine logo everywhere
Your logo image is now used in: the home page header and footer, the sign-in box, the app sidebar, the browser tab icon (favicon), the phone / install icons (including the maskable one), the social-share preview image, the legal and message pages, the staff analytics header and tab icon, the e-mails, and the top of the PDF reports. The small spots use the "B + spine" emblem cropped from your image (the full wording would be unreadable at 40 px); the big spots use the full logo. All files are in `static/img/` (`logo.png`, `logo-full.png`, `logo-full-small.png`, `icon-*.png`, `favicon.ico`, `og-image.png`) - replace them to change the logo later.
