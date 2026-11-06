"""
Builds docs/data.json for the map dashboard from visits_result.xlsx + project_sites.xlsx.
History is kept: new visits are merged into the existing data.json by visit_id,
so the daily 3-day lookback never erases older visits.
"""
import json
import os

import pandas as pd

VISITS_FILE = "visits_result.xlsx"
SITES_FILE = "project_sites.xlsx"
OUT = os.path.join("docs", "data.json")


def main():
    visits = pd.read_excel(VISITS_FILE, sheet_name="Visits")
    sites = pd.read_excel(SITES_FILE)

    old = {}
    if os.path.exists(OUT):
        with open(OUT, encoding="utf-8") as f:
            old = {v["id"]: v for v in json.load(f).get("visits", [])}

    for r in visits.itertuples():
        old[r.visit_id] = {
            "id": r.visit_id, "v": str(r.vehicle_code),
            "d": "" if pd.isna(r.device_id) else str(r.device_id),
            "p": str(r.project_code), "m": str(r.month),
            "e": pd.Timestamp(r.enter).strftime("%Y-%m-%d %H:%M"),
            "t": round(float(r.dwell_min), 1),
        }

    out = {
        "updated": pd.Timestamp.now().strftime("%Y-%m-%d %H:%M"),
        "sites": [{"code": str(s.project_code),
                   "name": "" if pd.isna(getattr(s, "project_name", None)) else str(s.project_name),
                   "lat": float(s.lat), "lon": float(s.lon), "r": float(s.radius_m)}
                  for s in sites.itertuples()],
        "visits": sorted(old.values(), key=lambda v: v["e"]),
    }
    os.makedirs("docs", exist_ok=True)
    with open(OUT, "w", encoding="utf-8") as f:
        json.dump(out, f, ensure_ascii=False, separators=(",", ":"))
    print(f"data.json: {len(out['visits'])} visits, {len(out['sites'])} sites")


if __name__ == "__main__":
    main()
