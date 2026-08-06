# MACD Sell Screener

Checks a list of tickers each day for a **MACD bearish crossover** (MACD line
crosses below its signal line) — the classic MACD "time to consider selling"
signal — and emails you when it fires. Runs automatically on GitHub Actions,
no server needed.

## How it works

1. `tickers.txt` holds the list of tickers to watch, one per line.
2. Every weekday at ~4:30pm ET (21:30 UTC), a GitHub Actions workflow runs
   `screener.py`, which pulls daily MACD values for each ticker from
   [Alpha Vantage](https://www.alphavantage.co) and checks for a bearish
   crossover.
3. Results are written to `results.md` and committed back to the repo, so
   you always have a running log you can check from your phone or browser.
4. If any ticker crossed over, you get an email.

## One-time setup

### 1. Create the repo

Create a new GitHub repo and push these files to it (or upload them
directly via the GitHub web UI — no git experience needed).

### 2. Get a free Alpha Vantage API key

Sign up at https://www.alphavantage.co/support/#api-key — it's free and
takes 30 seconds. Note: the free tier is capped at **25 requests/day**, so
keep your ticker list under ~20-25 names, or run less often.

### 3. Add repo secrets

In your repo: **Settings → Secrets and variables → Actions → New repository
secret**. Add these:

| Secret | Example value |
|---|---|
| `ALPHAVANTAGE_API_KEY` | your key from step 2 |
| `SMTP_SERVER` | `smtp-mail.outlook.com` (Hotmail/Outlook) or `smtp.gmail.com` (Gmail) |
| `SMTP_PORT` | `587` |
| `SMTP_USERNAME` | your full email address |
| `SMTP_PASSWORD` | an **app password** (see below — not your normal login password) |
| `EMAIL_FROM` | same as `SMTP_USERNAME` |
| `EMAIL_TO` | where you want alerts sent (can be the same address) |

**Getting an app password:**
- **Outlook/Hotmail**: account.microsoft.com → Security → Advanced security
  options → App passwords → create one, use it as `SMTP_PASSWORD`.
- **Gmail**: myaccount.google.com → Security → 2-Step Verification → App
  passwords → create one for "Mail".

Regular account passwords generally won't work with SMTP if 2FA is on —
use an app password.

### 4. Enable Actions

Go to the **Actions** tab in your repo and enable workflows if prompted.
That's it — it'll run automatically on the schedule.

## Updating the ticker list

Just edit or replace `tickers.txt` (one ticker per line, `#` for comments)
directly on GitHub — click the file, hit the pencil/edit icon, save. You
can also drag-and-drop a new `tickers.txt` via **Add file → Upload files**
to overwrite it. Any commit to `tickers.txt` automatically triggers an
immediate screener run in addition to the daily schedule.

## Running manually

**Actions tab → MACD Sell Screener → Run workflow** to trigger a check any
time, outside the schedule.

## Adjusting the signal or schedule

- Signal logic (bearish MACD/signal-line crossover) lives in
  `is_bearish_crossover()` in `screener.py`.
- MACD periods (12/26/9 standard) are set at the top of `screener.py`.
- Schedule is the `cron` line in `.github/workflows/screener.yml`
  (currently weekdays at 21:30 UTC).

## Disclaimer

This is a technical-indicator alert tool, not investment advice. MACD
crossovers can and do produce false signals — use your own judgment.
