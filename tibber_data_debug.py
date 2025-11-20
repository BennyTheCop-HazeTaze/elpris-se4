#!/usr/bin/env python3
# -*- coding: utf-8 -*-

import os
import sys
import json
import datetime as dt
import requests

# Tibber Data API (inte GraphQL)
BASE_URL = "https://data-api.tibber.com/v1"


def get_token():
    """
    Försök först med TIBBER_DATA_TOKEN, annars TIBBER_TOKEN.
    Du kan nöja dig med bara TIBBER_TOKEN om samma token funkar mot båda API:erna.
    """
    t = os.environ.get("TIBBER_DATA_TOKEN", "").strip()
    if not t:
        t = os.environ.get("TIBBER_TOKEN", "").strip()
    if not t:
        print("ERROR: Saknar TIBBER_DATA_TOKEN/TIBBER_TOKEN i miljön.", file=sys.stderr)
        sys.exit(2)
    return t


def api_get(path, params=None, token=None):
    url = BASE_URL + path
    headers = {
        "Authorization": f"Bearer {token}",
        "Accept": "application/json",
    }
    r = requests.get(url, headers=headers, params=params, timeout=30)
    print(f"\n=== GET {url} status {r.status_code} ===", file=sys.stderr)
    if r.status_code != 200:
        print("Svar:", r.text, file=sys.stderr)
        sys.exit(1)
    return r.json()


def main():
    token = get_token()

    # 1) HÄMTA HEM
    homes = api_get("/homes", token=token)
    print("\n--- /v1/homes ---")
    print(json.dumps(homes, indent=2, ensure_ascii=False))

    try:
        home = homes["homes"][0]
        home_id = home["id"]
    except Exception as e:
        print("Kunde inte plocka ut homeId:", e, file=sys.stderr)
        sys.exit(3)

    print(f"\nValt homeId: {home_id}\n")

    # 2) HÄMTA DEVICES FÖR HEMMET
    devices = api_get(f"/homes/{home_id}/devices", token=token)
    print("\n--- /v1/homes/{homeId}/devices ---")
    print(json.dumps(devices, indent=2, ensure_ascii=False))

    dev_list = devices.get("devices") or []
    if not dev_list:
        print("Inga devices hittades för hemmet.", file=sys.stderr)
        sys.exit(4)

    # 3) Försök hitta en device med history (Pulse)
    history_candidates = []
    for d in dev_list:
        info = d.get("info") or {}
        hist = d.get("supportedHistory") or {}
        resolutions = [r for r in (hist.get("resolutions") or [])]
        if resolutions:
            history_candidates.append(
                {
                    "id": d.get("id"),
                    "externalId": d.get("externalId"),
                    "name": info.get("name"),
                    "resolutions": resolutions,
                }
            )

    print("\n--- Devices med history-stöd ---")
    print(json.dumps(history_candidates, indent=2, ensure_ascii=False))

    if not history_candidates:
        print("Hittade ingen device med history-stöd.", file=sys.stderr)
        sys.exit(5)

    # Ta första kandidaten (förmodligen din Pulse)
    dev = history_candidates[0]
    dev_id = dev["id"]
    print(f"\nVald deviceId: {dev_id} (namn: {dev.get('name')})\n")

    # 4) HÄMTA HISTORY FÖR SENASTE 24H MED HOURLY-RESOLUTION
    now = dt.datetime.utcnow()
    since = (now - dt.timedelta(days=1)).isoformat(timespec="seconds") + "Z"
    until = now.isoformat(timespec="seconds") + "Z"

    params = {
        "since": since,
        "until": until,
        "resolution": "hour",
    }

    hist = api_get(f"/homes/{home_id}/devices/{dev_id}/history", params=params, token=token)

    print("\n--- /v1/homes/{homeId}/devices/{deviceId}/history (hour, sista 24h) ---")
    # Skriv bara de första 5 posterna så loggen inte blir gigantisk
    items = hist.get("items") or []
    preview = items[:5]
    print(json.dumps(preview, indent=2, ensure_ascii=False))

    # Extra: skriv bara ut nycklarna i data-fältet om de finns
    if preview:
        print("\n--- Nycklar i data-fältet på första posten ---")
        first_data = preview[0].get("data") or {}
        print(json.dumps(list(first_data.keys()), indent=2, ensure_ascii=False))


if __name__ == "__main__":
    main()
