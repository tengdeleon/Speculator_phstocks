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
ANTHROPIC_API_KEY = os.environ.get("ANTHROPIC_API_KEY", "YOUR_ANTHROPIC_API_KEY_HERE")
NTFY_TOPIC        = os.environ.get("NTFY_TOPIC", "YOUR_NTFY_TOPIC_HERE")  # e.g. "speculator-abc123"
NTFY_URL          = f"https://ntfy.sh/{NTFY_TOPIC}"
MAX_BUDGET        = int(os.environ.get("MAX_BUDGET", "5000"))

# ─── PSE HOLIDAYS 2026 ────────────────────────────────────────────────────────
PSE_HOLIDAYS = {
    "2026-01-01","2026-02-25","2026-04-02","2026-04-03","2026-04-09",
    "2026-05-01","2026-06-12","2026-08-31","2026-11-01","2026-11-30",
    "2026-12-08","2026-12-24","2026-12-25","2026-12-30","2026-12-31",
}

def is_trading_day(d: date) -> bool:
    if d.weekday() >= 5:  # Saturday=5, Sunday=6
        return False
    return d.isoformat() not in PSE_HOLIDAYS

def get_pht_now() -> datetime:
    from datetime import timezone
    utc_now = datetime.now(timezone.utc)
    pht = utc_now.utctimetuple()
    # PHT = UTC+8
    pht_now = datetime.utcnow() + timedelta(hours=8)
    return pht_now

def get_last_trading_day() -> date:
    d = date.today() - timedelta(days=1)
    while not is_trading_day(d):
        d -= timedelta(days=1)
    return d

# ─── FEE CALCULATOR ──────────────────────────────────────────────────────────
def calc_fees(buy_amt: float, sell_amt: float) -> dict:
    """DragonFi fee structure (verified Mar 2026)"""
    def fee(amt, is_sell):
        comm = amt * 0.0025
        vat  = comm * 0.12
        pse  = amt * 0.00005
        vatp = pse * 0.12
        sccp = amt * 0.0001
        stt  = amt * 0.001 if is_sell else 0  # CMEPA Law 0.1%
        return comm + vat + pse + vatp + sccp + stt
    return {
        "buy_fee":  fee(buy_amt, False),
        "sell_fee": fee(sell_amt, True),
    }

def get_board_lot(price: float) -> int:
    if price < 0.50:   return 10000
    if price < 5.00:   return 1000
    if price < 10.00:  return 1000
    if price < 20.00:  return 100
    if price < 50.00:  return 100
    if price < 100:    return 100
    if price < 200:    return 10
    if price < 500:    return 10
    if price < 1000:   return 10
    return 5

# ─── PSE DATA FETCHER ─────────────────────────────────────────────────────────
def fetch_pse_picks(budget: int) -> list[dict]:
    """Fetch latest PSE top gainers and compute picks via Claude + web search"""
    client = anthropic.Anthropic(api_key=ANTHROPIC_API_KEY)

    last_td = get_last_trading_day()
    date_str = last_td.strftime("%A, %B %d, %Y")

    system = (
        "You are a PSE stock trading assistant. "
        "After searching for data, respond ONLY with a raw JSON array — "
        "no markdown, no backticks, no explanation. Just the JSON array."
    )

    prompt = f"""Search filgit.com/pse-top-gainers and filgit.com/most-active-pse for the latest PSE stock data as of {date_str}.

Return the top 3 PSEi stocks to buy (entry price = close price) and sell next trading day for ~2% net profit.

Rules:
- Budget per trade: ₱{budget} max. One board lot must NOT exceed ₱{budget}.
- Board lot table: price<0.50=10000sh; 0.50-4.99=1000sh; 5-9.99=1000sh; 10-19.99=100sh; 20-49.99=100sh; 50-99.99=100sh; 100-199.99=10sh; 200-499.99=10sh; 500-999.99=10sh; 1000+=5sh
- DragonFi fees: buy_fee=(capital*0.0025*1.12)+(capital*0.00005*1.12)+(capital*0.0001); sell_fee=same+sell_value*0.001
- net_profit = (sell_price - close_price) * board_lot - buy_fee - sell_fee
- Pick stocks with strong upward momentum, high volume, board_lot*close_price <= ₱{budget}

Respond with ONLY a JSON array like this (no other text):
[
  {{
    "ticker": "IMI",
    "name": "Integrated Micro-Electronics",
    "close_price": 3.68,
    "board_lot": 1000,
    "capital": 3680.00,
    "sell_price": 3.81,
    "buy_fee": 10.66,
    "sell_fee": 14.34,
    "net_profit": 115.00,
    "net_pct": 3.1,
    "momentum_1d": 5.44,
    "volume": "3.04M",
    "reason": "one sentence why"
  }}
]"""

    messages = [{"role": "user", "content": prompt}]
    tools = [{"type": "web_search_20250305", "name": "web_search"}]
    final_text = ""
    iters = 0

    while iters < 8:
        iters += 1
        response = client.messages.create(
            model="claude-sonnet-4-20250514",
            max_tokens=2000,
            system=system,
            tools=tools,
            messages=messages,
        )

        # Append assistant response to history
        messages.append({"role": "assistant", "content": response.content})

        # Collect text
        for block in response.content:
            if block.type == "text":
                final_text = block.text

        if response.stop_reason == "end_turn":
            break

        if response.stop_reason == "tool_use":
            tool_results = []
            for block in response.content:
                if block.type == "tool_use":
                    # For web_search, the results come back in block.content
                    result_content = ""
                    if hasattr(block, "content") and block.content:
                        if isinstance(block.content, list):
                            result_content = "\n".join(
                                c.get("text", str(c)) if isinstance(c, dict) else str(c)
                                for c in block.content
                            )
                        else:
                            result_content = str(block.content)
                    else:
                        result_content = f"Search query: {json.dumps(block.input)}"

                    tool_results.append({
                        "type": "tool_result",
                        "tool_use_id": block.id,
                        "content": result_content or "Search completed.",
                    })
            messages.append({"role": "user", "content": tool_results})
            continue

        break

    # Parse JSON from response
    if not final_text:
        raise ValueError("No text response from Claude API")

    clean = final_text.strip()
    clean = clean.replace("```json", "").replace("```", "").strip()

    start = clean.find("[")
    end   = clean.rfind("]")
    if start == -1 or end == -1:
        raise ValueError(f"No JSON array found in response: {clean[:300]}")

    picks = json.loads(clean[start:end+1])
    return picks

# ─── NTFY NOTIFICATION ────────────────────────────────────────────────────────
def send_ntfy(picks: list[dict], budget: int, trade_date: str):
    """Send push notification via ntfy.sh"""

    if not picks:
        requests.post(NTFY_URL, headers={
            "Title": "📈 Speculator Agent",
            "Priority": "default",
            "Tags": "chart_with_downwards_trend"
        }, data="No valid picks found today.")
        return

    lines = [f"📅 {trade_date} | Budget ₱{budget:,}\n"]

    for i, p in enumerate(picks[:3], 1):
        lines.append(
            f"#{i} {p['ticker']} — {p['name']}\n"
            f"  Buy: ₱{p['close_price']} | Sell: ₱{p['sell_price']}\n"
            f"  Lot: {p['board_lot']:,} sh | Capital: ₱{p['capital']:,.2f}\n"
            f"  Net Profit: +₱{p['net_profit']:.2f} ({p['net_pct']:.1f}%)\n"
            f"  Momentum: +{p['momentum_1d']}% | Vol: {p.get('volume','—')}\n"
            f"  💡 {p.get('reason','')}\n"
        )

    lines.append("⚠️ Not financial advice. Set stop-loss before trading.")
    body = "\n".join(lines)

    resp = requests.post(
        NTFY_URL,
        data=body.encode("utf-8"),
        headers={
            "Title": f"📈 Speculator: Top 3 PSEi Picks",
            "Priority": "high",
            "Tags": "chart_with_upwards_trend,moneybag",
            "Content-Type": "text/plain; charset=utf-8",
        }
    )
    resp.raise_for_status()
    print(f"✅ Notification sent! Status: {resp.status_code}")

# ─── MAIN ─────────────────────────────────────────────────────────────────────
def main():
    pht_now = get_pht_now()
    today   = pht_now.date()

    print(f"🕘 Running Speculator Agent — PHT: {pht_now.strftime('%Y-%m-%d %H:%M:%S')}")

    # Check if today is a trading day
    if not is_trading_day(today):
        print("⏭ Today is not a trading day. Skipping.")
        send_ntfy([], MAX_BUDGET, today.strftime("%b %d, %Y"))
        return

    last_td = get_last_trading_day()
    date_str = last_td.strftime("%b %d, %Y")

    print(f"📊 Fetching picks based on {date_str} close prices...")

    try:
        picks = fetch_pse_picks(MAX_BUDGET)
        print(f"✅ Got {len(picks)} picks")
        for p in picks:
            print(f"   {p['ticker']}: Buy ₱{p['close_price']} → Sell ₱{p['sell_price']} | Net +₱{p['net_profit']:.2f}")

        send_ntfy(picks, MAX_BUDGET, date_str)

    except Exception as e:
        print(f"❌ Error: {e}")
        requests.post(NTFY_URL, headers={
            "Title": "📈 Speculator Agent — ERROR",
            "Priority": "high",
            "Tags": "warning",
        }, data=f"Error fetching picks: {str(e)}")

if __name__ == "__main__":
    main()
