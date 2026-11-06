"""
Step 1: Count how many times each vehicle visited each project site.

Input : inbox/*.xlsx         (vehicle_code, device_id, timestamp, lat, lon)
        project_sites.xlsx   (project_code, project_name, lat, lon, radius_m)
Output: visits_result.xlsx   (sheet "Visits" = one row per visit,
                              sheet "Summary" = counts per vehicle/project/month)

Run:  pip install pandas numpy openpyxl
      python analyze_visits.py
"""
import glob
import os
import sys

import numpy as np
import pandas as pd

# ---------------- SETTINGS ----------------
INBOX = "inbox"             # drop the daily GPS Excel files here
LOOKBACK_DAYS = 3           # each run re-analyses the last N days (use --backfill for ALL data)
SITES_FILE = "project_sites.xlsx"
OUT_FILE = "visits_result.xlsx"

GAP_MIN = 30         # no GPS point inside site for this long = visit ended
MIN_DWELL_MIN = 5    # ignore pass-by visits shorter than this

# Map YOUR Excel column names (left) to the standard names (right)
GPS_COLS = {
    "vehicle_code": "vehicle_code",
    "device_id": "device_id",
    "timestamp": "timestamp",
    "lat": "lat",
    "lon": "lon",
}
SITE_COLS = {
    "project_code": "project_code",
    "project_name": "project_name",
    "lat": "lat",
    "lon": "lon",
    "radius_m": "radius_m",
}
# ------------------------------------------


def haversine_m(lat1, lon1, lat2, lon2):
    """Distance in metres between points (numpy arrays or scalars)."""
    r = 6371000.0
    p1, p2 = np.radians(lat1), np.radians(lat2)
    dphi = p2 - p1
    dlmb = np.radians(lon2) - np.radians(lon1)
    a = np.sin(dphi / 2) ** 2 + np.cos(p1) * np.cos(p2) * np.sin(dlmb / 2) ** 2
    return 2 * r * np.arcsin(np.sqrt(a))


def load(backfill=False):
    files = [f for f in glob.glob(os.path.join(INBOX, "*.xlsx")) if not os.path.basename(f).startswith("~$")]
    if not files:
        sys.exit(f"ERROR: no .xlsx files in '{INBOX}' folder")
    print(f"Reading {len(files)} GPS file(s) from '{INBOX}'")
    gps = pd.concat([pd.read_excel(f) for f in files], ignore_index=True)
    gps = gps.rename(columns={v: k for k, v in GPS_COLS.items()})
    sites = pd.read_excel(SITES_FILE).rename(columns={v: k for k, v in SITE_COLS.items()})
    gps["timestamp"] = pd.to_datetime(gps["timestamp"])
    gps = gps.dropna(subset=["lat", "lon", "timestamp"])
    gps = gps[(gps.lat.between(-90, 90)) & (gps.lon.between(-180, 180))]
    gps = gps.drop_duplicates(subset=["vehicle_code", "timestamp"])
    window_start = None
    if not backfill:
        window_start = gps["timestamp"].max().normalize() - pd.Timedelta(days=LOOKBACK_DAYS)
        # read 1 extra day so visits that began just before the window keep their true start time
        gps = gps[gps["timestamp"] >= window_start - pd.Timedelta(days=1)]
    gps = gps.sort_values(["vehicle_code", "timestamp"]).reset_index(drop=True)
    return gps, sites, window_start


def points_inside_sites(gps, sites):
    """Return GPS points that fall inside any site (a point can match several overlapping sites)."""
    parts = []
    for s in sites.itertuples():
        d = haversine_m(gps["lat"].values, gps["lon"].values, s.lat, s.lon)
        hit = gps[d <= s.radius_m].copy()
        hit["project_code"] = s.project_code
        hit["project_name"] = getattr(s, "project_name", s.project_code)
        parts.append(hit)
    if not parts:
        return pd.DataFrame()
    return pd.concat(parts, ignore_index=True)


def build_visits(inside):
    inside = inside.sort_values(["vehicle_code", "project_code", "timestamp"]).copy()
    keys = ["vehicle_code", "project_code"]
    gap = inside.groupby(keys)["timestamp"].diff()
    new_visit = gap.isna() | (gap > pd.Timedelta(minutes=GAP_MIN))
    inside["visit_no"] = new_visit.groupby([inside[k] for k in keys]).cumsum()

    visits = (
        inside.groupby(keys + ["visit_no"])
        .agg(
            device_id=("device_id", "first"),
            project_name=("project_name", "first"),
            enter=("timestamp", "min"),
            exit=("timestamp", "max"),
            points=("timestamp", "count"),
            lat=("lat", "mean"),
            lon=("lon", "mean"),
        )
        .reset_index()
    )
    visits["dwell_min"] = ((visits["exit"] - visits["enter"]).dt.total_seconds() / 60).round(1)
    visits = visits[visits["dwell_min"] >= MIN_DWELL_MIN].copy()
    visits["month"] = visits["enter"].dt.strftime("%Y-%m")
    visits["visit_id"] = (
        visits["vehicle_code"].astype(str) + "|" + visits["project_code"].astype(str) + "|"
        + visits["enter"].dt.strftime("%Y%m%d%H%M")
    )
    cols = ["visit_id", "vehicle_code", "device_id", "project_code", "project_name",
            "month", "enter", "exit", "dwell_min", "points", "lat", "lon"]
    return visits[cols].sort_values(["vehicle_code", "enter"]).reset_index(drop=True)


def summarize(visits):
    return (
        visits.groupby(["month", "vehicle_code", "device_id", "project_code", "project_name"])
        .agg(visit_count=("visit_id", "count"), total_dwell_min=("dwell_min", "sum"),
             avg_dwell_min=("dwell_min", "mean"))
        .round(1)
        .reset_index()
    )


def main():
    backfill = "--backfill" in sys.argv
    gps, sites, window_start = load(backfill)
    print(f"GPS rows: {len(gps):,} | Sites: {len(sites)}")
    inside = points_inside_sites(gps, sites)
    if inside.empty:
        sys.exit("ERROR: no GPS points fall inside any site. Check lat/lon order and radius_m.")
    visits = build_visits(inside)
    if window_start is not None:
        visits = visits[visits["enter"] >= window_start].reset_index(drop=True)
    summary = summarize(visits)
    with pd.ExcelWriter(OUT_FILE) as xw:
        visits.to_excel(xw, sheet_name="Visits", index=False)
        summary.to_excel(xw, sheet_name="Summary", index=False)
    print(f"Visits found: {len(visits):,} -> saved to {OUT_FILE}")
    print(summary.head(10).to_string(index=False))


if __name__ == "__main__":
    main()
