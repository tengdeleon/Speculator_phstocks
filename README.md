# PH-Speculator

A scheduled agent that screens the Philippine Stock Exchange for short-term
trade candidates each morning and pushes the shortlist to my phone. Built in
Python, deployed on GitHub Actions, runs unattended on a market-hours schedule.

It is a small **production automation**, not a notebook: it triggers on a cron,
pulls live data, applies an explicit decision rule, accounts for real broker
costs, and delivers a result — every trading day, with no one watching.

```
GitHub Actions cron  (9:45 AM & 10:45 AM PHT, weekdays)
        │
        ▼
  fetch live PSE data ───────────(Claude API + web search)
        │
        ▼
  screen candidates ──── price momentum · volume · upward trend
        │
        ▼
  size & cost the trade ─ ₱5,000 board-lot cap · DragonFi round-trip fees · 2% net target
        │
        ▼
  push the shortlist ────────────(ntfy.sh)──▶ iPhone
```

## What it does

1. **Triggers** twice each weekday morning via a GitHub Actions schedule, near
   the open and mid-morning.
2. **Fetches** current PSE prices, volume, and trend via the Claude API with web
   search, returning structured JSON.
3. **Screens** the board for momentum, above-average volume, and a clean upward
   trend — the conditions for a buy-today / sell-next-session play.
4. **Costs the trade** against the real DragonFi fee schedule so the 2% target is
   *net*, not gross.
5. **Pushes** the ranked shortlist to my phone through ntfy.sh.

## The decision logic (made explicit)

Screening is rule-based, not a black box:

- **Candidate filter:** positive short-term momentum, volume above its recent
  average, and price holding an upward trend.
- **Position sizing:** one board lot must not exceed **₱5,000** — the per-trade
  budget cap.
- **Net-profit gate:** the 2% target is checked *after* a full round-trip cost
  model, so a "2% mover" that the fees would eat is rejected.

**Round-trip cost model (DragonFi, CMEPA Law):**

| Component | Rate | Side |
|---|---|---|
| Commission | 0.25% | buy + sell |
| VAT on commission | 12% of commission | buy + sell |
| PSE transaction fee | 0.005% | buy + sell |
| VAT on PSE fee | 12% of PSE fee | buy + sell |
| SCCP | 0.01% | buy + sell |
| Stock transaction tax (STT) | 0.10% | sell only |

Modeling the sell-side STT and the VAT-on-fees is the difference between a
trade that looks profitable and one that actually clears costs.

## Schedule & deployment

- **CI as the runtime.** A GitHub Actions workflow runs the agent on a cron in
  PHT; there is no server to maintain.
- **Secrets** (API key, ntfy topic) are stored as GitHub Actions secrets, never
  in the repo.
- **Holiday-safe.** PSE non-trading days return no actionable data; the agent
  enforces strict JSON and exits cleanly instead of failing the run or pushing
  noise.

## Configuration

Copy `.env.example` and set:

```
ANTHROPIC_API_KEY=    # Claude API
NTFY_TOPIC=           # ntfy.sh topic the phone subscribes to
MAX_PESOS_PER_TRADE=5000
NET_PROFIT_TARGET=0.02
```

Run locally: `python speculator.py` — or let the scheduled workflow run it.

## What I'd harden for production

- **Persistence & dedup** — log each shortlist so the same name isn't re-pushed
  across the 9:45 and 10:45 runs.
- **Data-source resilience** — validate the fetched figures against a second
  source; retry with backoff on a bad response.
- **Backtesting** — replay the screen over historical sessions to measure the
  net-of-fees hit rate before trusting it with size.
- **Observability** — alert on a failed or empty run rather than silently
  skipping a morning.

## Disclaimer

A personal automation for my own use. It surfaces candidates; it does **not**
place trades and is **not** financial advice. Markets carry risk; do your own
research.
