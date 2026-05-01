name: Speculator Agent — Daily PSEi Picks

on:
  schedule:
    # 9:45 AM PHT = 01:45 UTC, Monday to Friday
    - cron: '45 1 * * 1-5'
  workflow_dispatch:  # allows manual trigger from GitHub Actions tab

jobs:
  run-speculator:
    runs-on: ubuntu-latest

    steps:
      - name: Checkout repository
        uses: actions/checkout@v4

      - name: Set up Python
        uses: actions/setup-python@v5
        with:
          python-version: '3.11'

      - name: Install dependencies
        run: pip install anthropic requests

      - name: Run Speculator Agent
        env:
          ANTHROPIC_API_KEY: ${{ secrets.ANTHROPIC_API_KEY }}
          NTFY_TOPIC: ${{ secrets.NTFY_TOPIC }}
          MAX_BUDGET: ${{ secrets.MAX_BUDGET }}
        run: python speculator.py
