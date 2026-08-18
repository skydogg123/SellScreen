#!/usr/bin/env python3
"""
MACD Sell Signal Screener
--------------------------
Reads a list of tickers from tickers.txt, pulls daily MACD values for each
from Alpha Vantage, and checks two triggers for each ticker:

  1. Bearish crossover: the MACD line crosses BELOW its signal line
     (the classic MACD "sell" signal).
  2. Declining MACD: today's MACD value is lower than yesterday's MACD
     value (momentum weakening day-over-day, even without a full
     crossover).

Results are written to results.md (committed back to the repo by the
GitHub Actions workflow). An email is sent every run: a signal alert if
either trigger fired for any ticker, otherwise a confirmation that
nothing triggered.

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


def is_macd_declining(points):
    """True if today's MACD value is lower than yesterday's MACD value."""
    today, yesterday = points[0], points[1]
    return today["macd"] < yesterday["macd"]


def send_email_alert(crossover_signals, declining_signals, errors=None):
    """Always sends a daily email: an alert listing whichever triggers
    fired, otherwise a confirmation that nothing triggered."""
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

    any_signals = bool(crossover_signals or declining_signals)

    if any_signals:
        subject_tickers = sorted(set(
            [s["ticker"] for s in crossover_signals] + [s["ticker"] for s in declining_signals]
        ))
        subject = f"MACD Alert: {', '.join(subject_tickers)}"
        lines = []

        if crossover_signals:
            lines.append("Bearish crossover (MACD crossed below signal line):\n")
            for s in crossover_signals:
                lines.append(f"  - {s['ticker']}: MACD {s['macd']:.4f} crossed below signal {s['signal']:.4f} on {s['date']}")
            lines.append("")

        if declining_signals:
            lines.append("MACD declining day-over-day:\n")
            for s in declining_signals:
                lines.append(f"  - {s['ticker']}: MACD {s['macd']:.4f} today vs {s['prev_macd']:.4f} yesterday on {s['date']}")
            lines.append("")
    else:
        subject = "MACD Daily Check: no signals today"
        lines = ["Checked all tickers today — no bearish crossovers and no MACD declines detected."]

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

    crossover_signals = []
    declining_signals = []
    errors = []
    checked = []

    for i, ticker in enumerate(tickers):
        try:
            points = fetch_macd(ticker)
            crossed = is_bearish_crossover(points)
            declining = is_macd_declining(points)

            checked.append({
                "ticker": ticker,
                "date": points[0]["date"],
                "macd": points[0]["macd"],
                "signal": points[0]["signal"],
                "prev_macd": points[1]["macd"],
                "sell_signal": crossed,
                "declining": declining,
            })

            if crossed:
                crossover_signals.append({
                    "ticker": ticker,
                    "date": points[0]["date"],
                    "macd": points[0]["macd"],
                    "signal": points[0]["signal"],
                })

            if declining:
                declining_signals.append({
                    "ticker": ticker,
                    "date": points[0]["date"],
                    "macd": points[0]["macd"],
                    "prev_macd": points[1]["macd"],
                })
        except Exception as e:
            errors.append(f"{ticker}: {e}")
            print(f"Error checking {ticker}: {e}", file=sys.stderr)

        if i < len(tickers) - 1:
            time.sleep(SECONDS_BETWEEN_CALLS)

    write_results(checked, errors)
    send_email_alert(crossover_signals, declining_signals, errors)


def write_results(checked, errors):
    now = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
    lines = [f"# MACD Sell Screener Results\n", f"_Last run: {now}_\n"]

    crossovers = [c for c in checked if c["sell_signal"]]
    decliners = [c for c in checked if c["declining"]]

    if crossovers:
        lines.append("## Bearish crossovers (MACD crossed below signal line)\n")
        for s in crossovers:
            lines.append(f"- **{s['ticker']}** on {s['date']} (MACD {s['macd']:.4f} / Signal {s['signal']:.4f})")
        lines.append("")

    if decliners:
        lines.append("## MACD declining day-over-day\n")
        for s in decliners:
            lines.append(f"- **{s['ticker']}** on {s['date']} (MACD {s['macd']:.4f} vs {s['prev_macd']:.4f} yesterday)")
        lines.append("")

    if not crossovers and not decliners:
        lines.append("## No signals today\n")

    lines.append("## All tickers checked\n")
    lines.append("| Ticker | Date | MACD | Signal | Prev MACD | Crossover | Declining |")
    lines.append("|---|---|---|---|---|---|---|")
    for c in checked:
        cross_flag = "YES" if c["sell_signal"] else ""
        decline_flag = "YES" if c["declining"] else ""
        lines.append(
            f"| {c['ticker']} | {c['date']} | {c['macd']:.4f} | {c['signal']:.4f} | "
            f"{c['prev_macd']:.4f} | {cross_flag} | {decline_flag} |"
        )

    if errors:
        lines.append("\n## Errors\n")
        for e in errors:
            lines.append(f"- {e}")

    with open(RESULTS_FILE, "w") as f:
        f.write("\n".join(lines) + "\n")


if __name__ == "__main__":
    main()
