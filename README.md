# JobApply Manager

Upload resumes → an AI model extracts structured profile data → search and apply to jobs on
**Naukri, LinkedIn (Easy Apply), Indeed and company career sites** from one scheduler, using a
different login/resume per site account.

> ## ⚠️ Read this first
> * **The Playwright worker must run on your own machine/server** (your PC is fine). Assisted login
>   needs a *visible* browser window, and job sites block or flag cloud/datacenter IPs. Do not run
>   the worker in a cloud sandbox.
> * **You are responsible for complying with each site's terms of service.** LinkedIn and others
>   restrict automated access; accounts can be limited or banned. Keep daily caps low (default 25 per
>   account), prefer `review` mode first, and use at your own risk.
> * **The app never solves or bypasses CAPTCHAs / bot checks / OTP.** When it meets one it stops,
>   takes a screenshot and marks the application `needs_human` for you to handle.
> * **It never guesses.** Unknown form fields, screening questions, logins, account-creation walls and
>   consent checkboxes stop the attempt (`needs_human`) instead of being invented.
> * **Site selectors are best-effort.** Job sites change their HTML often and the adapters cannot be
>   tested against the real sites from CI (tests use local HTML fixtures). Expect to adjust the `SEL`
>   dictionary at the top of `backend/app/adapters/<site>.py` now and then.

## How it works

```
 React UI (5173) ──► FastAPI (8000) ──► MySQL / SQLite
                          ▲                  ▲
                          │ creates runs     │ reads schedules, writes runs/jobs/applications/logs
                          │                  │
                    Worker (APScheduler, persisted in DB) ──► Playwright (one isolated context per account)
                          │                                     ├─ adapters: naukri · linkedin · indeed · company_site
                          └─ LLM (Gemini / Groq / Ollama / Claude): resume parsing, job match scoring, form-field mapping
```

* **Resume Manager** – PDF/DOCX upload, text extraction (pdfplumber / python-docx), Claude extracts a
  structured profile (JSON + normalized `skills` table). You can correct everything in the UI; edits are
  never overwritten unless you press *Re-parse*. Several resumes per user, one default, per-account choice.
* **Site accounts** – several per site. Session cookies (Playwright `storage_state`) and optional
  passwords are Fernet-encrypted in the DB; cookies never touch disk in plain text and are never logged.
  *Assisted login* opens a visible browser, types the email/password you saved on the account and presses Login; you only handle OTP/CAPTCHA by hand. The session is then saved.
* **Search profiles** – keywords, location, experience, salary, job type, posted-within-N-days,
  excluded companies, sites, company apply URLs.
* **Schedules** – daily at HH:MM, weekdays, or cron; choose profile + accounts + daily cap + match
  threshold. *Apply on all sites at once* runs the selected accounts in parallel (bounded concurrency)
  with random human-like delays (default 20–60 s between applications) and a per-account daily cap
  (default 25). Modes: **dry_run** (find + score only) · **review** (queue for one-click approval) ·
  **auto** (submit).
* **Match scoring** – Claude scores every job 0–100 against your resume and stores the reasoning; only
  jobs ≥ the schedule's threshold proceed.
* **Screening questions** – answered from your resume (name, contact, total experience…) and your
  **answer bank** (notice period, expected CTC, relocation…). Unknown questions go to the **Review
  queue**; answering one can save it to the bank and re-queues the job.
* **Dashboard** – counts per site/day, per-account quota, run history; **Applications** history with
  filters; live **run log** over Server-Sent Events.

## Setup – run everything locally

You need: **Python 3.11+**, **Node 20+**, **Git**. Docker is optional (see Option B).

### 1. Get the code and configure `.env`
```bash
git clone https://github.com/kamalnathsoftware/jobapply_manager.git
cd jobapply_manager
cp .env.example .env          # Windows PowerShell: Copy-Item .env.example .env
```
Edit `.env`:

| Variable | Meaning |
|---|---|
| `DATABASE_URL` | `sqlite:///./jobapply.db` (simplest) **or** `mysql+pymysql://user:pass@localhost:3306/jobapply` |
| `JWT_SECRET` | `python -c "import secrets;print(secrets.token_urlsafe(48))"` |
| `FERNET_KEY` | `python -c "from cryptography.fernet import Fernet;print(Fernet.generate_key().decode())"` – **back it up**; without it saved sessions/passwords can't be decrypted |
| `LLM_PROVIDER` | `gemini` (default, free tier) · `groq` (free tier) · `ollama` (local, free) · `anthropic` (paid) – see *AI provider* below |
| `GEMINI_API_KEY` / `GROQ_API_KEY` | free keys from https://aistudio.google.com/apikey and https://console.groq.com/keys |
| `OLLAMA_BASE_URL` / `OLLAMA_MODEL` | local Ollama, e.g. `http://localhost:11434/v1` and `qwen2.5:7b` |
| `ANTHROPIC_API_KEY` / `ANTHROPIC_MODEL` | only if `LLM_PROVIDER=anthropic` (Claude Pro does **not** include API credits) |
| `PLAYWRIGHT_HEADLESS` | `true` for unattended runs; `false` to watch the browser |
| `APPLY_GAP_MIN_S` / `APPLY_GAP_MAX_S` | random pause between applications (seconds) |
| `INDEED_BASE_URL` | your country's Indeed domain, e.g. `https://in.indeed.com` |
| `CORS_ORIGINS`, `STORAGE_DIR` | defaults are fine locally |

### AI provider (free options)
Resume parsing, job scoring and company-site field mapping all go through one provider, chosen with `LLM_PROVIDER`:

| Provider | Cost | Setup |
|---|---|---|
| `gemini` (default) | free tier, rate-limited | create a key at aistudio.google.com/apikey → `GEMINI_API_KEY=` |
| `groq` | free tier, rate-limited | key at console.groq.com/keys → `LLM_PROVIDER=groq`, `GROQ_API_KEY=` |
| `ollama` | free, runs on your PC (8 GB+ RAM) | install Ollama, `ollama pull qwen2.5:7b`, `LLM_PROVIDER=ollama` |
| `anthropic` | paid per token | `LLM_PROVIDER=anthropic`, `ANTHROPIC_API_KEY=` |

**Several providers at once:** list them in `.env`, e.g. `LLM_PROVIDER=gemini,groq,ollama` – each request tries them in
that order and falls back to the next if one fails (rate limit, denied key, offline, bad JSON). You can also manage this in the
app: **Settings → AI providers** lets you enable providers, reorder them, paste API keys (stored encrypted, applied immediately
without restarting) and *Test* each one. Settings saved in the app override `.env`; *Reset to .env* removes them.

Notes: free tiers throttle requests – the app retries automatically with back-off, so large runs are slower.
Free/small models make more mistakes: **review your parsed resume** (Resumes → *Review / edit parsed data*), and
keep `dry_run`/`review` mode until scores look sensible. Your resume and job text are sent to the provider you
choose (not for `ollama`). Model names change over time – if a provider reports an unknown model, set
`GEMINI_MODEL` / `GROQ_MODEL` to a current one from the provider's docs.

### 2. Option A – native (recommended; needed for assisted login anyway)

**Backend** (terminal 1):
```bash
cd backend
python -m venv ../.venv
# macOS/Linux: source ../.venv/bin/activate      Windows PowerShell: ..\.venv\Scripts\Activate.ps1
pip install -r requirements.txt
playwright install chromium          # one-time browser download
alembic upgrade head                 # creates the tables
uvicorn app.main:app --reload        # API on http://localhost:8000  (docs at /docs)
```
**Worker** (terminal 2 – same venv, same `.env`; executes runs, schedules and the approval queue):
```bash
cd backend
# activate the venv as above
python -m app.workers.main
```
**Frontend** (terminal 3):
```bash
cd frontend
npm install
npm run dev                          # http://localhost:5173
```

### 2. Option B – Docker for MySQL + API + UI
```bash
# in .env set MYSQL_ROOT_PASSWORD / MYSQL_PASSWORD (any values)
docker compose up --build            # mysql, backend, worker, frontend
```
Docker is convenient for the database and UI, but the containerised worker is **headless only** and cannot
open the assisted-login browser. For real use run the **backend and worker natively** (Option A) and point
`DATABASE_URL` at the MySQL container (`mysql+pymysql://jobapply:<password>@localhost:3306/jobapply`)
— e.g. `docker compose up mysql`.

### 3. First use (in the UI at http://localhost:5173)
1. **Register**, then **Settings → Answer bank**: add notice period, expected CTC, relocation, … .
2. **Resumes**: upload a PDF/DOCX, open *Review / edit parsed data*, fix anything wrong, set the default.
3. **Accounts**: add one per site login (label, email, resume, daily cap) → **Log in (assisted)** → a browser
   window opens on this machine and your saved email/password are typed in for you; complete any OTP/CAPTCHA yourself. It
   closes automatically and the session is saved (status `active`). Logging in does not start applying – that is the next step.
4. **Search profiles**: uploading a resume now creates one automatically (job title, experience range and location from the parsed resume) plus a daily 09:00 schedule in `review` mode, so matches wait in the Review Queue until you approve them. Use "Auto-create search & schedule" on a resume to redo it after adding accounts. Or create one by hand (keywords, location, sites; for company sites paste apply URLs).
5. **Schedules**: pick profile + accounts, mode **dry_run** first, threshold e.g. 60 → **▶ Apply on all selected sites now**
   and watch the live log. Check the **Applications** page for scores and reasoning.
6. Switch to **review** (approve jobs yourself in **Review queue**) and finally **auto** once you trust it.

## Tests and lint
```bash
cd backend
pip install -r requirements-dev.txt
ruff check .
pytest                                # 100+ tests: parsing, scoring, scheduler/quota logic, adapters on mock pages
cd ../frontend && npm run typecheck && npm run build
```
Adapter tests drive headless Chromium against local HTML fixtures in `backend/tests/fixtures/` – they never
contact real job sites. If your Chromium is not the one Playwright expects, set
`PLAYWRIGHT_CHROMIUM_EXECUTABLE=/path/to/chrome` when running pytest; browser tests are skipped when no
browser can be launched.

## Project layout
```
backend/app/{api,core,models,schemas,services,adapters,workers}   backend/alembic/   backend/tests/
frontend/src/{pages,components,api,hooks}                         docker-compose.yml  .env.example
```
* `adapters/base.py` – `SiteAdapter` interface: `search()`, `get_job()`, `apply()`; `NeedsHuman` signals a stop.
* `adapters/{naukri,linkedin,indeed,company_site}.py` – site plugins (selectors in each file's `SEL`).
  Register new ones in `adapters/__init__.py`.
* `adapters/forms.py`, `wizard.py`, `guards.py` – shared form discovery/filling, multi-step wizards, CAPTCHA/login-wall detection.
* `services/runner.py` – search → dedupe → score → dry-run / queue / apply, quotas, parallel accounts.
* `workers/main.py` – APScheduler (jobs persisted in the DB), run claiming, approval-queue processing.
* New migration: `scripts/newmig.sh <rev> <name>` (autogenerates against a scratch SQLite DB).

## Troubleshooting
* **“Run now” stays `pending`** – the worker isn't running (`python -m app.workers.main`).
* **Assisted login window does nothing / closes at once** – see `storage/logs/assisted_login_<account id>.log`; run `playwright install chromium` once.
* **Assisted login says “No display available”** – the backend runs in Docker/SSH; run it natively on your desktop.
* **Account shows `needs_login` / `needs_human`** – a session expired or the site showed a check; use *Re-login*.
* **Resume `parse_failed`** – check `LLM_PROVIDER` and its key in `.env` (Settings shows what is configured), restart backend + worker, then *Re-parse*.
* **A site adapter finds nothing / can't apply** – the site's markup changed; update `SEL` in the adapter.
* **PowerShell blocks `Activate.ps1`** – `Set-ExecutionPolicy -Scope CurrentUser RemoteSigned`.

## Security notes
Secrets live only in `.env` (git-ignored). Passwords and cookies are encrypted with Fernet and never logged;
the API never returns them. Resume files and screenshots are stored under `STORAGE_DIR` (screenshots can show
personal data – keep that folder private). Change `JWT_SECRET`/passwords before exposing anything beyond localhost.


### Worker status
The Schedules page shows whether the worker is running (it writes a heartbeat file in `STORAGE_DIR`). If it is not, click **Start worker** (or **Run now**, which starts it for you); its output goes to `STORAGE_DIR/logs/worker.log`. A run stuck in `pending` can be cancelled from the same page.
