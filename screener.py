#!/usr/bin/env python3
"""
MACD Sell Signal Screener
--------------------------
Reads a list of tickers from tickers.txt, pulls daily MACD values for each
from Alpha Vantage, and flags any ticker whose MACD line has just crossed
BELOW its signal line (the classic MACD bearish/"sell" crossover).

Results are written to results.md (committed back to the repo by the
GitHub Actions workflow) and, if any signals fire, an email alert is sent.

Environment variables required:
  ALPHAVANTAGE_API_KEY   - free key from https://www.alphavantage.co/support/#api-key
  SMTP_SERVER             e.g. smtp-mail.outlook.com or smtp.gmail.com
  SMTP_PORT               e.g. 587
  SMTP_USERNAME            login for the SMTP account
  SMTP_PASSWORD            app password / SMTP password
  EMAIL_FROM               sender address (usually same as SMTP_USERNAME)
  EMAIL_TO                 where to send alerts (can be same as EMAIL_FROM)
"""

import os
import sys
import time
import smtplib
from email.mime.text import MIMEText
from datetime import datetime, timezone

import requests

ALPHA_VANTAGE_URL = "https://www.alphavantage.co/query"
API_KEY = os.environ.get("ALPHAVANTAGE_API_KEY", "")
TICKERS_FILE = os.path.join(os.path.dirname(__file__), "tickers.txt")
RESULTS_FILE = os.path.join(os.path.dirname(__file__), "results.md")

# Standard MACD settings
FAST_PERIOD = 12
SLOW_PERIOD = 26
SIGNAL_PERIOD = 9

# Alpha Vantage free tier is rate-limited (5 calls/min, 25 calls/day as of
# 2024). This delay keeps us under the per-minute limit; if your ticker
# list is long you may need to run less often or upgrade your plan.
SECONDS_BETWEEN_CALLS = 15


def load_tickers():
    if not os.path.exists(TICKERS_FILE):
        print(f"No tickers.txt found at {TICKERS_FILE}", file=sys.stderr)
        return []
    with open(TICKERS_FILE) as f:
        tickers = [line.strip().upper() for line in f if line.strip() and not line.startswith("#")]
    return tickers


def fetch_macd(ticker):
    """Return the two most recent (date, macd, signal) points for a ticker."""
    params = {
        "function": "MACD",
        "symbol": ticker,
        "interval": "daily",
        "series_type": "close",
        "fastperiod": FAST_PERIOD,
        "slowperiod": SLOW_PERIOD,
        "signalperiod": SIGNAL_PERIOD,
        "apikey": API_KEY,
    }
    resp = requests.get(ALPHA_VANTAGE_URL, params=params, timeout=30)
    resp.raise_for_status()
    data = resp.json()

    if "Note" in data or "Information" in data:
        # Rate limit / API key issue
        msg = data.get("Note") or data.get("Information")
        raise RuntimeError(f"Alpha Vantage API limit/notice for {ticker}: {msg}")

    series = data.get("Technical Analysis: MACD")
    if not series:
        raise RuntimeError(f"No MACD data returned for {ticker}: {data}")

    # Dates come back as keys; sort descending to get most recent first
    dates = sorted(series.keys(), reverse=True)[:2]
    if len(dates) < 2:
        raise RuntimeError(f"Not enough MACD history for {ticker}")

    points = []
    for d in dates:
        points.append({
            "date": d,
            "macd": float(series[d]["MACD"]),
            "signal": float(series[d]["MACD_Signal"]),
        })
    return points  # [today, yesterday]


def is_bearish_crossover(points):
    """True if MACD was >= signal yesterday and is < signal today."""
    today, yesterday = points[0], points[1]
    was_above_or_equal = yesterday["macd"] >= yesterday["signal"]
    now_below = today["macd"] < today["signal"]
    return was_above_or_equal and now_below


def send_email_alert(signals, errors=None):
    """Always sends a daily email: a sell alert if signals fired, otherwise
    a confirmation that nothing triggered."""
    errors = errors or []

    smtp_server = os.environ.get("SMTP_SERVER")
    smtp_port = int(os.environ.get("SMTP_PORT", "587"))
    smtp_username = os.environ.get("SMTP_USERNAME")
    smtp_password = os.environ.get("SMTP_PASSWORD")
    email_from = os.environ.get("EMAIL_FROM", smtp_username)
    email_to = os.environ.get("EMAIL_TO", smtp_username)

    if not all([smtp_server, smtp_username, smtp_password, email_to]):
        print("SMTP secrets not fully configured; skipping email.", file=sys.stderr)
        return

    if signals:
        subject = f"MACD Sell Alert: {', '.join(s['ticker'] for s in signals)}"
        lines = ["MACD sell signal (bearish crossover) fired for:\n"]
        for s in signals:
            lines.append(f"  - {s['ticker']}: MACD {s['macd']:.4f} crossed below signal {s['signal']:.4f} on {s['date']}")
    else:
        subject = "MACD Daily Check: no sell signals today"
        lines = ["Checked all tickers today — no MACD bearish crossovers detected."]

    if errors:
        lines.append("\nNote: some tickers could not be checked:")
        for e in errors:
            lines.append(f"  - {e}")

    body = "\n".join(lines)

    msg = MIMEText(body)
    msg["Subject"] = subject
    msg["From"] = email_from
    msg["To"] = email_to

    with smtplib.SMTP(smtp_server, smtp_port) as server:
        server.starttls()
        server.login(smtp_username, smtp_password)
        server.sendmail(email_from, [email_to], msg.as_string())
    print(f"Email alert sent to {email_to}")
   


def main():
    if not API_KEY:
        print("ALPHAVANTAGE_API_KEY is not set.", file=sys.stderr)
        sys.exit(1)

    tickers = load_tickers()
    if not tickers:
        print("No tickers to check.")
        return

    signals = []
    errors = []
    checked = []

    for i, ticker in enumerate(tickers):
        try:
            points = fetch_macd(ticker)
            crossed = is_bearish_crossover(points)
            checked.append({
                "ticker": ticker,
                "date": points[0]["date"],
                "macd": points[0]["macd"],
                "signal": points[0]["signal"],
                "sell_signal": crossed,
            })
            if crossed:
                signals.append({
                    "ticker": ticker,
                    "date": points[0]["date"],
                    "macd": points[0]["macd"],
                    "signal": points[0]["signal"],
                })
        except Exception as e:
            errors.append(f"{ticker}: {e}")
            print(f"Error checking {ticker}: {e}", file=sys.stderr)

        if i < len(tickers) - 1:
            time.sleep(SECONDS_BETWEEN_CALLS)

    write_results(checked, errors)
    send_email_alert(signals, errors)


def write_results(checked, errors):
    now = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
    lines = [f"# MACD Sell Screener Results\n", f"_Last run: {now}_\n"]

    signals = [c for c in checked if c["sell_signal"]]
    if signals:
        lines.append("## Sell signals (MACD crossed below signal line)\n")
        for s in signals:
            lines.append(f"- **{s['ticker']}** on {s['date']} (MACD {s['macd']:.4f} / Signal {s['signal']:.4f})")
        lines.append("")
    else:
        lines.append("## No sell signals today\n")

    lines.append("## All tickers checked\n")
    lines.append("| Ticker | Date | MACD | Signal | Sell Signal |")
    lines.append("|---|---|---|---|---|")
    for c in checked:
        flag = "YES" if c["sell_signal"] else ""
        lines.append(f"| {c['ticker']} | {c['date']} | {c['macd']:.4f} | {c['signal']:.4f} | {flag} |")

    if errors:
        lines.append("\n## Errors\n")
        for e in errors:
            lines.append(f"- {e}")

    with open(RESULTS_FILE, "w") as f:
        f.write("\n".join(lines) + "\n")


if __name__ == "__main__":
    main()
