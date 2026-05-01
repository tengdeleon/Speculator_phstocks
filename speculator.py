#!/usr/bin/env python3
"""
Speculator Agent — PSEi Stock Picker with ntfy Push Notifications
Runs daily at 9:45 AM Philippine Time (PHT / UTC+8)
Sends top 3 picks to your phone via ntfy.sh
"""

import os
import json
import requests
from datetime import datetime, date, timedelta
import anthropic

# ─── CONFIG ──────────────────────────────────────────────────────────────────
ANTHROPIC_API_KEY = os.environ.get("ANTHROPIC_API_KEY", "")
NTFY_TOPIC        = os.environ.get("NTFY_TOPIC", "")
NTFY_URL          = f"https://ntfy.sh/{NTFY_TOPIC}"
MAX_BUDGET        = int(os.environ.get("MAX_BUDGET", "5000"))

# PICK_MODE controls which day's closing prices are used:
#   "previous" = last trading day's close prices (default, always has data)
#   "current"  = today's prices (only meaningful if market is open/just closed)
PICK_MODE = os.environ.get("PICK_MODE", "previous").lower()

# ─── PSE HOLIDAYS 2026 ────────────────────────────────────────────────────────
PSE_HOLIDAYS = {
    "2026-01-01","2026-02-25","2026-04-02","2026-04-03","2026-04-09",
    "2026-05-01","2026-06-12","2026-08-31","2026-11-01","2026-11-30",
    "2026-12-08","2026-12-24","2026-12-25","2026-12-30","2026-12-31",
}

def is_trading_day(d: date) -> bool:
    if d.weekday() >= 5:
        return False
    return d.isoformat() not in PSE_HOLIDAYS

def get_pht_now() -> datetime:
    return datetime.utcnow() + timedelta(hours=8)

def get_last_trading_day() -> date:
    d = get_pht_now().date() - timedelta(days=1)
    while not is_trading_day(d):
        d -= timedelta(days=1)
    return d

def get_target_date() -> tuple:
    """Returns (target_date, mode_label) based on PICK_MODE"""
    today = get_pht_now().date()
    if PICK_MODE == "current" and is_trading_day(today):
        return today, "Current Trading Day"
    else:
        last_td = get_last_trading_day()
        return last_td, "Previous Trading Day"

# ─── FEE CALCULATOR ──────────────────────────────────────────────────────────
def calc_fees(buy_amt: float, sell_amt: float) -> dict:
    def fee(amt, is_sell):
        comm = amt * 0.0025
        vat  = comm * 0.12
        pse  = amt * 0.00005
        vatp = pse * 0.12
        sccp = amt * 0.0001
        stt  = amt * 0.001 if is_sell else 0
        return comm + vat + pse + vatp + sccp + stt
    return {
        "buy_fee":  fee(buy_amt, False),
        "sell_fee": fee(sell_amt, True),
    }

def get_board_lot(price: float) -> int:
    if price < 0.50:  return 10000
    if price < 5.00:  return 1000
    if price < 10.00: return 1000
    if price < 20.00: return 100
    if price < 50.00: return 100
    if price < 100:   return 100
    if price < 200:   return 10
    if price < 500:   return 10
    if price < 1000:  return 10
    return 5

# ─── PSE DATA FETCHER ─────────────────────────────────────────────────────────
def fetch_pse_picks(budget: int, target_date: date, mode_label: str) -> list:
    client = anthropic.Anthropic(api_key=ANTHROPIC_API_KEY)
    date_str = target_date.strftime("%A, %B %d, %Y")

    system = (
        "You are a PSE stock trading assistant. "
        "After searching for data, respond ONLY with a raw JSON array. "
        "No markdown, no backticks, no explanation. Just the JSON array."
    )

    prompt = f"""Search filgit.com/pse-top-gainers for PSE stock data as of {date_str} ({mode_label}).

Return top 3 PSEi stocks to buy and sell next trading day for 2% net profit.

Rules:
- Budget: PHP {budget} max. One board lot must NOT exceed PHP {budget}.
- Board lot: price<0.50=10000sh; 0.50-4.99=1000sh; 5-9.99=1000sh; 10-19.99=100sh; 20-49.99=100sh; 50-99.99=100sh; 100-199.99=10sh; 200-499.99=10sh; 500-999.99=10sh; 1000+=5sh
- DragonFi fees: buy_fee=(capital*0.0025*1.12)+(capital*0.00005*1.12)+(capital*0.0001); sell_fee=same+sell_value*0.001
- net_profit = (sell_price - close_price) * board_lot - buy_fee - sell_fee
- Pick stocks with strong upward momentum, high volume, board_lot*close_price <= PHP {budget}

Respond with ONLY a JSON array, no other text:
[{{"ticker":"IMI","name":"Integrated Micro-Electronics","close_price":3.68,"board_lot":1000,"capital":3680.00,"sell_price":3.81,"buy_fee":10.66,"sell_fee":14.34,"net_profit":115.00,"net_pct":3.1,"momentum_1d":5.44,"volume":"3.04M","reason":"one sentence why"}}]"""

    messages = [{"role": "user", "content": prompt}]
    tools = [{"type": "web_search_20250305", "name": "web_search"}]
    final_text = ""
    iters = 0

    while iters < 8:
        iters += 1
        response = client.messages.create(
            model="claude-sonnet-4-6",
            max_tokens=2000,
            system=system,
            tools=tools,
            messages=messages,
        )

        messages.append({"role": "assistant", "content": response.content})

        for block in response.content:
            if hasattr(block, "type") and block.type == "text":
                final_text = block.text

        if response.stop_reason == "end_turn":
            break

        if response.stop_reason == "tool_use":
            tool_results = []
            for block in response.content:
                if hasattr(block, "type") and block.type == "tool_use":
                    result_content = "Search completed."
                    if hasattr(block, "content") and block.content:
                        if isinstance(block.content, list):
                            result_content = "\n".join(
                                c.get("text", str(c)) if isinstance(c, dict) else str(c)
                                for c in block.content
                            )
                        else:
                            result_content = str(block.content)
                    tool_results.append({
                        "type": "tool_result",
                        "tool_use_id": block.id,
                        "content": result_content,
                    })
            messages.append({"role": "user", "content": tool_results})
            continue

        break

    if not final_text:
        raise ValueError("No text response from Claude API")

    clean = final_text.strip().replace("```json", "").replace("```", "").strip()
    start = clean.find("[")
    end   = clean.rfind("]")
    if start == -1 or end == -1:
        raise ValueError(f"No JSON array found: {clean[:300]}")

    return json.loads(clean[start:end+1])

# ─── NTFY NOTIFICATION ────────────────────────────────────────────────────────
def send_ntfy(picks: list, budget: int, trade_date: str, mode_label: str):
    if not picks:
        requests.post(NTFY_URL, headers={
            "Title": "Speculator Agent",
            "Priority": "default",
            "Tags": "chart_with_downwards_trend",
        }, data="No valid picks found today.")
        return

    lines = [f"PSEi Picks | {trade_date} ({mode_label}) | Budget PHP {budget:,}\n"]
    for i, p in enumerate(picks[:3], 1):
        lines.append(
            f"#{i} {p['ticker']} - {p['name']}\n"
            f"  Buy: PHP {p['close_price']} | Sell: PHP {p['sell_price']}\n"
            f"  Lot: {p['board_lot']:,} sh | Capital: PHP {p['capital']:,.2f}\n"
            f"  Net Profit: +PHP {p['net_profit']:.2f} ({p['net_pct']:.1f}%)\n"
            f"  Momentum: +{p['momentum_1d']}% | Vol: {p.get('volume','')}\n"
            f"  {p.get('reason','')}\n"
        )
    lines.append("Not financial advice. Set stop-loss before trading.")
    body = "\n".join(lines)

    resp = requests.post(
        NTFY_URL,
        data=body.encode("utf-8"),
        headers={
            "Title": f"Speculator: Top 3 PSEi Picks ({mode_label})",
            "Priority": "high",
            "Tags": "chart_with_upwards_trend,moneybag",
            "Content-Type": "text/plain; charset=utf-8",
        }
    )
    resp.raise_for_status()
    print(f"Notification sent! Status: {resp.status_code}")

# ─── MAIN ─────────────────────────────────────────────────────────────────────
def main():
    pht_now = get_pht_now()
    today   = pht_now.date()

    print(f"Running Speculator Agent - PHT: {pht_now.strftime('%Y-%m-%d %H:%M:%S')}")
    print(f"PICK_MODE: {PICK_MODE}")

    # Determine target date based on PICK_MODE
    target_date, mode_label = get_target_date()
    date_str = target_date.strftime("%b %d, %Y")
    print(f"Using {mode_label}: {date_str}")

    # Skip only if today is not a trading day AND mode is current
    if PICK_MODE == "current" and not is_trading_day(today):
        print("PICK_MODE=current but today is not a trading day. Switching to previous trading day.")
        target_date = get_last_trading_day()
        mode_label  = "Previous Trading Day"
        date_str    = target_date.strftime("%b %d, %Y")

    print(f"Fetching picks for {date_str}...")

    try:
        picks = fetch_pse_picks(MAX_BUDGET, target_date, mode_label)
        print(f"Got {len(picks)} picks")
        for p in picks:
            print(f"  {p['ticker']}: Buy PHP {p['close_price']} -> Sell PHP {p['sell_price']} | Net +PHP {p['net_profit']:.2f}")
        send_ntfy(picks, MAX_BUDGET, date_str, mode_label)

    except Exception as e:
        print(f"Error: {e}")
        requests.post(NTFY_URL, headers={
            "Title": "Speculator Agent - ERROR",
            "Priority": "high",
            "Tags": "warning",
        }, data=f"Error: {str(e)}")

if __name__ == "__main__":
    main()
