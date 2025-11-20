#!/usr/bin/env python3
# -*- coding: utf-8 -*-

import os, sys, json, datetime as dt
import requests

API_URL = "https://api.tibber.com/v1-beta/gql"

QUERY = """
query PriceAndConsumption($homeId: ID) {
  viewer {
    homes(id: $homeId) {
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
    # Tibber använder normalt Z (UTC); gör det till aware datetime
    return dt.datetime.fromisoformat(s.replace("Z", "+00:00"))

def build_price_rows(prices):
    """
    Tar en lista av prisobjekt från Tibber (hourly eller quarter-hourly)
    och returnerar listor med:
      - SEK_per_kWh
      - time_start
      - time_end

    time_end sätts till nästa periods start, och sista raden får samma längd
    som föregående intervall (fallback 1h om bara en rad).
    """
    if not prices:
        return []

    # sortera på startsAt för säkerhets skull
    ps = sorted(prices, key=lambda p: p["startsAt"])
    starts = [parse_iso(p["startsAt"]) for p in ps]

    rows = []
    for i, p in enumerate(ps):
        start_dt = starts[i]
        if i + 1 < len(ps):
            end_dt = starts[i + 1]
        else:
            # sista punkten: använd samma delta som tidigare intervall om möjligt,
            # annars anta 1 timme
            if len(starts) >= 2:
                delta = starts[-1] - starts[-2]
            else:
                delta = dt.timedelta(hours=1)
            end_dt = start_dt + delta

        rows.append({
            "SEK_per_kWh": round(float(p["total"]), 5),
            "time_start": start_dt.isoformat(),
            "time_end": end_dt.isoformat(),
        })
    return rows

def aggregate_consumption(nodes):
    """
    Summerar kWh och kostnad från Tibber consumption.nodes.
    """
    kwh = 0.0
    cost = 0.0
    for n in nodes or []:
        if n.get("consumption") is not None:
            kwh += float(n["consumption"])
        if n.get("cost") is not None:
            cost += float(n["cost"])
    return round(kwh, 3), round(cost, 2)

def main():
    token = os.environ.get("TIBBER_TOKEN", "").strip()
    home_id = os.environ.get("TIBBER_HOME_ID", "").strip() or None
    if not token:
        print("ERROR: Saknar TIBBER_TOKEN i miljön.", file=sys.stderr)
        sys.exit(2)

    headers = {
        "Authorization": f"Bearer {token}",
        "Content-Type": "application/json",
    }
    payload = {"query": QUERY, "variables": {"homeId": home_id}}

   r = requests.post(API_URL, headers=headers, json=payload, timeout=30)

    # Debug: skriv ut fel från Tibber om något är galet
    if r.status_code != 200:
        print(f"ERROR from Tibber API (status {r.status_code}):", file=sys.stderr)
        try:
            print(r.text, file=sys.stderr)
        except Exception:
            pass
        sys.exit(1)

    data = r.json()

    try:
        homes = data["data"]["viewer"]["homes"]
        if not homes:
            raise KeyError("Inga homes i Tibber-kontot.")
        home = homes[0]

        sub = home["currentSubscription"]
        price_info = sub["priceInfo"] if sub else None
        today_prices = price_info["today"] if price_info else []
        tomorrow_prices = price_info["tomorrow"] if price_info else []

        day_nodes = home["consumptionLastDay"]["nodes"]
        week_nodes = home["consumptionLastWeek"]["nodes"]
    except Exception as e:
        print(f"ERROR: Kunde inte tolka Tibber-svaret: {e}", file=sys.stderr)
        print(json.dumps(data, indent=2, ensure_ascii=False))
        sys.exit(3)

    os.makedirs("data", exist_ok=True)

    # Prisfiler (som din HTML redan använder)
    with open("data/today.json", "w", encoding="utf-8") as f:
        json.dump(build_price_rows(today_prices), f, ensure_ascii=False)

    rows_tomorrow = build_price_rows(tomorrow_prices)
    if rows_tomorrow:
        with open("data/tomorrow.json", "w", encoding="utf-8") as f:
            json.dump(rows_tomorrow, f, ensure_ascii=False)

    # Stats för Dakboard (sista 24h + 7 dagar)
    day_kwh, day_cost = aggregate_consumption(day_nodes)
    week_kwh, week_cost = aggregate_consumption(week_nodes)

    stats = {
        "last24h": {
            "kwh": day_kwh,
            "cost": day_cost,
        },
        "last7d": {
            "kwh": week_kwh,
            "cost": week_cost,
        },
    }
    with open("data/stats.json", "w", encoding="utf-8") as f:
        json.dump(stats, f, ensure_ascii=False)

    print(
        f"Priser idag: {len(today_prices)} st, imorgon: {len(tomorrow_prices)} st | "
        f"24h: {day_kwh} kWh / {day_cost} kr | 7d: {week_kwh} kWh / {week_cost} kr"
    )

if __name__ == "__main__":
    main()
