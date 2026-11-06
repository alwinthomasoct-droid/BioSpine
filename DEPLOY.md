# BioSpine v5 — run it, then launch it

## 1. Run on your computer
```
python -m venv venv
venv\Scripts\activate            # Mac/Linux:  source venv/bin/activate
pip install -r requirements.txt
copy .env.example .env           # Mac/Linux:  cp .env.example .env   -> then fill in SECRET_KEY and GEMINI_API_KEY, keep DEBUG=True
python manage.py migrate
python manage.py createsuperuser # your staff login for /admin/ and /staff/analytics/
python manage.py check_ai        # (optional) tests your Gemini key and tells you which model answers
python manage.py check_email you@example.com   # sends a test email and explains plainly what is wrong if it fails
python manage.py runserver
```
Open http://127.0.0.1:8000 · admin: `/admin/` · analytics: `/staff/analytics/`

## 2. Put it on GitHub (safely)
`.gitignore` already blocks `.env`, `db.sqlite3` and backups. Check with `git status` that none of them is listed, then:
```
git init
git add .
git commit -m "BioSpine v4"
git branch -M main
git remote add origin https://github.com/<you>/biospine.git
git push -u origin main
```
> If a real API key was ever committed or shared, **create a new key** in Google AI Studio and delete the old one.

## 3. Launch (Render + free PostgreSQL)
| Step | What to do |
|---|---|
| 1 | Create a PostgreSQL database (Neon, Supabase, Render, Railway… check each one's *current* free-tier limits — some free databases expire or pause). Copy its connection string. |
| 2 | On render.com: **New → Blueprint** → pick your GitHub repo (it reads `render.yaml`). |
| 3 | Fill in the variables it asks for: `SITE_URL` (https://your-app.onrender.com), `DATABASE_URL`, `GEMINI_API_KEY`, `OPERATOR_NAME`, `CONTACT_EMAIL`. |
| 4 | After the first deploy open the Render **Shell** and run `python manage.py createsuperuser`. |
| 5 | Visit `/healthz` (should say ok), then sign up on the live site. |

Free web services "sleep" when idle (first visit after a break is slow) and have no persistent disk, which is why the database must be external PostgreSQL.

## 3b. Turn the AI assistant off (optional)
Set `AI_ENABLED=False`. The AI Physio, AI check-up and the Chats tab disappear from the whole website. They also stay hidden automatically while `GEMINI_API_KEY` is empty.

## 4. Make emails work (verification, password reset, weekly report)
Create a free SMTP account (Brevo, Gmail app-password, Mailgun…) and set `EMAIL_HOST`, `EMAIL_PORT`, `EMAIL_HOST_USER`, `EMAIL_HOST_PASSWORD`, `DEFAULT_FROM_EMAIL`.
Test: run `python manage.py check_email you@example.com` (it prints the real error if sending fails), then sign up with a second address and confirm the email arrives. Gmail: use an *App password* and port 587 (or 465 with `EMAIL_USE_SSL=True`); set `DEFAULT_FROM_EMAIL` to the same address you log in with. **Only then** set `REQUIRE_EMAIL_VERIFICATION=True` (it blocks AI features for unverified accounts, which stops bots burning your AI quota).

Weekly report: set `CRON_SECRET` to a long random string, then create a free job on cron-job.org that calls
`https://your-site/cron/weekly-report/?key=<CRON_SECRET>` every Monday 08:00.

## 5. Backups
* Production: turn on your PostgreSQL provider's automatic backups.
* Extra copy: `python manage.py backup_data` (gzip JSON in `backups/`, keeps the newest 14). Contains password hashes — keep it private.

## 6. Pre-launch checklist
- [ ] `DEBUG` is **False** on the host, `SECRET_KEY` is long and random, `ALLOWED_HOSTS`/`SITE_URL` are your real domain
- [ ] `python manage.py check_ai` prints WORKING for your key
- [ ] Sign-up → confirmation email → sign-in → AI question → sign-out all work on the live URL, on a real phone
- [ ] You filled `OPERATOR_NAME` and `CONTACT_EMAIL`, and **had the Privacy Policy / Terms reviewed** (they are plain-language templates, not legal advice)
- [ ] Delete-my-account and Download-my-data tested with a throw-away account
- [ ] Optional: `SENTRY_DSN` set so crashes reach you
- [ ] Soft-launch to ~10 people and watch `/staff/analytics/` for a week

## 7. Things that cannot be fixed in code
* **Web Bluetooth does not exist in iPhone/iPad browsers or Firefox.** Android Chrome/Edge and desktop Chrome/Edge work. The app detects this and says so; the demo and history still work everywhere.
* **Wi-Fi (`ws://`) mode cannot work from an https website** (browsers block it). Bluetooth/USB are the live-site options.
* Google renames/retires Gemini models regularly. The code tries a chain of models and `check_ai` shows what your key can use; set `GEMINI_MODEL` to pin one.
