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
    """Convert ISO8601 string to timezone-aware datetime."""
    return dt.datetime.fromisoformat(s.replace("Z", "+00:00"))

def build_price_rows(prices):
    """Return time_start/time_end rows supporting 1h or 15-min intervals."""
    if not prices:
        return []

    ps = sorted(prices, key=lambda p: p["startsAt"])
    starts = [parse_iso(p["startsAt"]) for p in ps]

    rows = []
    for i, p in enumerate(ps):
        start_dt = starts[i]

        if i + 1 < len(ps):
            end_dt = starts[i + 1]
        else:
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
    """Sum kWh and cost."""
    kwh = 0.0
    cost = 0.0
    for n in nodes or []:
        kwh += float(n.get("consumption") or 0)
        cost += float(n.get("cost") or 0)
    return round(kwh, 3), round(cost, 2)

def main():
    token = os.environ.get("TIBBER_TOKEN", "").strip()

    if not token:
        print("ERROR: Missing TIBBER_TOKEN", file=sys.stderr)
        sys.exit(2)

    headers = {
        "Authorization": f"Bearer {token}",
        "Content-Type": "application/json"
    }

    payload = {"query": QUERY}

    r = requests.post(API_URL, headers=headers, json=payload, timeout=30)

    if r.status_code != 200:
        print("ERROR: Tibber returned status", r.status_code, file=sys.stderr)
        print("Response:", r.text, file=sys.stderr)
        sys.exit(1)

    data = r.json()

    try:
        homes = data["data"]["viewer"]["homes"]
        if not homes:
            raise KeyError("No homes found")

        home = homes[0]

        sub = home.get("currentSubscription")
        price_info = sub.get("priceInfo") if sub else None
        today_prices = price_info.get("today") if price_info else []
        tomorrow_prices = price_info.get("tomorrow") if price_info else []

        cons_day = home.get("consumptionLastDay") or {}
        cons_week = home.get("consumptionLastWeek") or {}

        day_nodes = cons_day.get("nodes") or []
        week_nodes = cons_week.get("nodes") or []

    except Exception as e:
        print("ERROR parsing Tibber data:", e, file=sys.stderr)
        print(json.dumps(data, indent=2, ensure_ascii=False), file=sys.stderr)
        sys.exit(3)

    os.makedirs("data", exist_ok=True)

    # Write today.json
    with open("data/today.json", "w", encoding="utf-8") as f:
        json.dump(build_price_rows(today_prices), f, ensure_ascii=False)

    # Write tomorrow.json
    rows_tomorrow = build_price_rows(tomorrow_prices)
    if rows_tomorrow:
        with open("data/tomorrow.json", "w", encoding="utf-8") as f:
            json.dump(rows_tomorrow, f, ensure_ascii=False)

    # Stats
    day_kwh, day_cost = aggregate_consumption(day_nodes)
    week_kwh, week_cost = aggregate_consumption(week_nodes)

    stats = {
        "last24h": {"kwh": day_kwh, "cost": day_cost},
        "last7d": {"kwh": week_kwh, "cost": week_cost}
    }

    with open("data/stats.json", "w", encoding="utf-8") as f:
        json.dump(stats, f, ensure_ascii=False)

    print("[OK] today:", len(today_prices), "entries")
    print("[OK] consumption last 24h:", day_kwh, "kWh")
    print("[OK] consumption last 7d:", week_kwh, "kWh")


if __name__ == "__main__":
    main()
