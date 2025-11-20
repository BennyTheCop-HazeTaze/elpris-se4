#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""
Hämtar förbrukning & kostnad från Tibber (GraphQL) och skriver till data/stats.json

Statistik:
- last24h:   senaste 24 timmarna (timupplöst)
- last7d:    senaste 7 hela dygn
- thisMonth: innevarande månad (summa av dagliga värden)

Kräver:
  TIBBER_TOKEN      = ditt vanliga Tibber API-token (GraphQL)
  TIBBER_HOME_ID    = (valfritt) specifikt home-id; annars används första hemmet
"""

import os
import sys
import json
import datetime as dt
import requests

API_URL = "https://api.tibber.com/v1-beta/gql"


# ----------------- Hjälpfunktioner ----------------- #

def get_token() -> str:
    token = os.environ.get("TIBBER_TOKEN", "").strip()
    if not token:
        print("ERROR: TIBBER_TOKEN saknas i miljön.", file=sys.stderr)
        sys.exit(2)
    return token


def tibber_gql(query: str, variables: dict | None, token: str) -> dict:
    headers = {
        "Authorization": f"Bearer {token}",
        "Content-Type": "application/json",
    }
    r = requests.post(API_URL, headers=headers, json={"query": query, "variables": variables or {}}, timeout=30)
    if r.status_code != 200:
        print(f"ERROR: Tibber GraphQL HTTP {r.status_code}", file=sys.stderr)
        print(r.text, file=sys.stderr)
        sys.exit(1)

    data = r.json()
    if "errors" in data and data["errors"]:
        print("ERROR: Tibber GraphQL errors:", file=sys.stderr)
        print(json.dumps(data["errors"], indent=2, ensure_ascii=False), file=sys.stderr)
        sys.exit(1)

    return data["data"]


def resolve_home_id(token: str) -> str:
    env_home_id = os.environ.get("TIBBER_HOME_ID", "").strip()
    if env_home_id:
        return env_home_id

    q = """
    query {
      viewer {
        homes {
          id
          appNickname
          address { address1 city }
        }
      }
    }
    """
    data = tibber_gql(q, None, token)
    homes = data.get("viewer", {}).get("homes") or []
    if not homes:
        print("ERROR: Hittade inga homes i Tibber-kontot.", file=sys.stderr)
        sys.exit(3)

    home = homes[0]
    hid = home["id"]
    nick = home.get("appNickname") or ""
    addr = home.get("address") or {}
    print(
        f"INFO: Använder homeId={hid} "
        f"({nick or 'utan nickname'}, {addr.get('address1') or ''} {addr.get('city') or ''})",
        file=sys.stderr,
    )
    return hid


def parse_date(s: str) -> dt.date:
    # Tibber använder ISO8601, t.ex. "2025-11-20T00:00:00+01:00"
    return dt.datetime.fromisoformat(s).date()


def sum_nodes(nodes, limit=None, filter_month=None):
    """
    nodes: lista av {from, consumption, cost, currency}
    limit: om satt → summera bara de sista 'limit' noderna
    filter_month: (year, month) → summera bara noder i den månaden
    """
    if not nodes:
        return {"kwh": 0.0, "cost": 0.0, "currency": None}

    # sortera på tid för säkerhets skull
    nodes_sorted = sorted(nodes, key=lambda n: n.get("from") or "")

    if limit is not None:
        nodes_sorted = nodes_sorted[-limit:]

    total_kwh = 0.0
    total_cost = 0.0
    currency = None

    for n in nodes_sorted:
        try:
            c = n.get("consumption")
            cost = n.get("cost")
            if filter_month is not None:
                d = parse_date(n["from"])
                if (d.year, d.month) != filter_month:
                    continue

            if c is not None:
                total_kwh += float(c)
            if cost is not None:
                total_cost += float(cost)
            if not currency:
                currency = n.get("currency")
        except Exception:
            continue

    return {"kwh": round(total_kwh, 3), "cost": round(total_cost, 2), "currency": currency}


# ----------------- Huvudlogik ----------------- #

def main():
    token = get_token()
    home_id = resolve_home_id(token)

    # En enda query som hämtar tim- och dagsdata
    q = """
    query($homeId: ID!) {
      viewer {
        home(id: $homeId) {
          timeZone
          consumptionHourly: consumption(resolution: HOURLY, last: 48) {
            nodes {
              from
              to
              consumption
              cost
              currency
            }
          }
          consumptionDaily: consumption(resolution: DAILY, last: 31) {
            nodes {
              from
              to
              consumption
              cost
              currency
            }
          }
        }
      }
    }
    """

    data = tibber_gql(q, {"homeId": home_id}, token)
    home = data.get("viewer", {}).get("home") or {}
    hourly_nodes = (home.get("consumptionHourly") or {}).get("nodes") or []
    daily_nodes = (home.get("consumptionDaily") or {}).get("nodes") or []

    today = dt.date.today()
    ym = (today.year, today.month)

    last24h = sum_nodes(hourly_nodes, limit=24)
    last7d = sum_nodes(daily_nodes, limit=7)
    this_month = sum_nodes(daily_nodes, filter_month=ym)

    stats = {
        "generated_at": dt.datetime.utcnow().isoformat(timespec="seconds") + "Z",
        "last24h": last24h,
        "last7d": last7d,
        "thisMonth": this_month,
    }

    os.makedirs("data", exist_ok=True)
    out_path = os.path.join("data", "stats.json")
    with open(out_path, "w", encoding="utf-8") as f:
        json.dump(stats, f, ensure_ascii=False, indent=2)

    print(
        "OK: stats.json uppdaterad | "
        f"24h: {last24h['kwh']} kWh / {last24h['cost']} {last24h['currency']} | "
        f"7d: {last7d['kwh']} kWh / {last7d['cost']} {last7d['currency']} | "
        f"månad: {this_month['kwh']} kWh / {this_month['cost']} {this_month['currency']}",
        file=sys.stderr,
    )


if __name__ == "__main__":
    main()
