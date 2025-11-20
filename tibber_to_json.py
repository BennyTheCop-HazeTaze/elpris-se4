#!/usr/bin/env python3
# -*- coding: utf-8 -*-

import os
import sys
import json
import datetime as dt
import requests

API_URL = "https://api.tibber.com/v1-beta/gql"

QUERY = """
query PriceAndConsumption {
  viewer {
    homes {
      id
      currentSubscription {
        priceInfo {
          today {
            startsAt
            total
            currency
          }
          tomorrow {
            startsAt
            total
            currency
          }
        }
      }
      consumptionLastDay: consumption(resolution: HOURLY, last: 24) {
        nodes {
          from
          to
          consumption
          cost
        }
      }
      consumptionLastWeek: consumption(resolution: DAILY, last: 7) {
        nodes {
          from
          to
          consumption
          cost
        }
      }
    }
  }
}
"""

def parse_iso(s: str) -> dt.datetime:
    """Convert ISO8601 string from Tibber into a timezone-aware datetime."""
    return dt.datetime.fromisoformat(s.replace("Z", "+00:00"))

def build_price_rows(prices):
    """
    Accepts price rows from Tibber (can be hourly OR 15-minute), and returns:
    [
        { "SEK_per_kWh": float,
          "time_start": iso string,
          "time_end": iso string }
    ]
    time_end is taken from the next row. Last row uses previous interval length.
    """
    if not prices:
        return []

    # sort by timestamp just in case
    ps = sorted(prices, key=lambda p: p["startsAt"])
    starts = [parse_iso(p["startsAt"]) for p in ps]

    rows = []
    for i, p in enumerate(ps):
        start_dt = starts[i]

        # determine end time
        if i + 1 < len(ps):
            end_dt = starts[i + 1]
        else:
            # fallback duration = same as previous interval or 1 hour
            if len(starts) >= 2:
                delta = starts[-1] - starts[-2]
            else:
                delta = dt.timedelta(hours=1)
            end_dt = start_dt + delta

        rows.append({
            "SEK_per_kWh": round(float(p["total"]), 5),
            "time_start": start_dt.isoformat(),
            "time_end": end_dt.isoformat()
        })

    return rows

def aggregate_consumption(nodes):
    """Sum kWh and cost for 24h or 7 days."""
    kwh = 0.0
    cost = 0.0
    for n in nodes or []:
        kwh += float(n.get("consumption") or 0)
        cost += float(n.get("cost") or 0)
    return round(kwh, 3), round(cost, 2)

def main():
    token = os.environ.get("TIBBER_TOKEN", "").strip()

    if not token:
        print("ERROR: Missing TIBBER_TOKEN environment variable.", file=sys.stderr)
        sys.exit(2)

    headers = {
        "Authorization": f"Bearer {token}",
        "Content-Type": "application/json"
    }

    payload = {
        "query": QUERY
    }

    # --- API request ---
    r = requests.post(API_URL, headers=headers, json=payload, timeout=30)

    if r.status_code != 200:
        print(f"ERROR: Tibber API returned {r.status_code}", file=sys.stderr)
        print("Response:", r.text, file=sys.stderr)
        sys.exit(1)

    data = r.json()

    # --- Parse output ---
    try:
        homes = data["data"]["viewer"]["homes"]
        if not homes:
            raise KeyError("No homes returned from Tibber API")

        # Ta första hemmet
        home = homes[0]

        sub = home["currentSubscription"]
        price_info = sub["priceInfo"] if sub else None
        today_prices = price_info["today"] if price_info else []
        tomorrow_prices = price_info["tomorrow"] if price_info else []

        day_nodes = home["consumptionLastDay"]["nodes"]
        week_nodes = home["consumptionLastWeek"]["nodes"]

    except Exception as e:
        print("ERROR parsing Tibber data:", e, file=sys.stderr)
        print(json.dumps(data, indent=2, ensure_ascii=False), file=sys.stderr)
        sys.exit(3)

    # Ensure output folder exists
    os.makedirs("data", exist_ok=True)

    # --- Price JSON (Dakboard graph already uses this format) ---
    with open("data/today.json", "w", encoding="utf-8") as f:
        json.dump(build_price_rows(today_prices), f, ensure_ascii=False)

    rows_tomorrow = build_price_rows(tomorrow_prices)
    if rows_tomorrow:
        with open("data/tomorrow.json", "w", encoding="utf-8") as f:
            json.dump(rows_tomorrow, f, ensure_ascii=False)

    # --- Consumption stats (24h + 7d) ---
    day_kwh, day_cost = aggregate_consumption(day_nodes)
    week_kwh, week_cost = aggregate_consumption(week_nodes)

    stats = {
        "last24h": {
            "kwh": day_kwh,
            "cost": day_cost
        },
        "last7d": {
            "kwh": week_kwh,
            "cost": week_cost
        }
    }

    with open("data/stats.json", "w", encoding="utf-8") as f:
        json.dump(stats, f, ensure_ascii=False)

    print(
        f"[OK] Prices today: {len(today_prices)} entries | "
        f"24h consumption: {day_kwh} kWh / {day_cost} kr | "
        f"7d consumption: {week_kwh} kWh / {week_cost} kr"
    )


if __name__ == "__main__":
    main()
