"""
Step 0: Find candidate project locations using ONLY the GPS data.

How it works
  1. Detect STOPS: a vehicle stays within STOP_RADIUS_M for at least STOP_MIN_MIN minutes.
  2. CLUSTER stops from all vehicles that are close together (DBSCAN).
  3. Each cluster = a candidate site. Busy clusters (many stops, many vehicles) are
     most likely real project sites, depots, fuel stations, etc.

Input : gps_export.xlsx  (vehicle_code, device_id, timestamp, lat, lon)
Output: candidate_sites.xlsx

Then YOU:
  - open candidate_sites.xlsx, check each row on Google Maps (map_link column)
  - delete rows that are NOT projects (depot, fuel station, restaurant, home)
  - fill in project_name
  - save as project_sites.xlsx  -> use with analyze_visits.py

Run:  pip install pandas numpy openpyxl scikit-learn
      python discover_sites.py
"""
import numpy as np
import pandas as pd
from sklearn.cluster import DBSCAN

# ---------------- SETTINGS ----------------
GPS_FILE = "gps_export.xlsx"
OUT_FILE = "candidate_sites.xlsx"

STOP_RADIUS_M = 50       # vehicle must stay inside this circle to count as stopped
STOP_MIN_MIN = 10        # ...for at least this many minutes
CLUSTER_EPS_M = 150      # stops closer than this are merged into one site
MIN_STOPS = 3            # a site needs at least this many stops to be listed
MIN_RADIUS_M = 100       # smallest radius suggested for a site
LONG_STAY_HOURS = 8      # stops longer than this are probably depot/parking/home

GPS_COLS = {  # your column name (left) -> standard name (right)
    "vehicle_code": "vehicle_code",
    "device_id": "device_id",
    "timestamp": "timestamp",
    "lat": "lat",
    "lon": "lon",
}
# ------------------------------------------


def to_xy(lat, lon, lat0):
    """Flat-earth metres, accurate enough for small distances."""
    return lon * 111320.0 * np.cos(np.radians(lat0)), lat * 110540.0


def detect_stops(g):
    """g = one vehicle's points sorted by time. Returns list of stop dicts."""
    t = g["timestamp"].values.astype("datetime64[s]").astype("int64")
    lat, lon = g["lat"].values, g["lon"].values
    x, y = to_xy(lat, lon, lat.mean())
    n, i, stops = len(g), 0, []
    while i < n:
        j = i + 1
        while j < n and np.hypot(x[j] - x[i], y[j] - y[i]) <= STOP_RADIUS_M:
            j += 1
        dur_min = (t[j - 1] - t[i]) / 60
        if j - i >= 2 and dur_min >= STOP_MIN_MIN:
            stops.append({
                "vehicle_code": g["vehicle_code"].iloc[0],
                "device_id": g["device_id"].iloc[0],
                "start": g["timestamp"].iloc[i],
                "end": g["timestamp"].iloc[j - 1],
                "dur_h": dur_min / 60,
                "lat": lat[i:j].mean(),
                "lon": lon[i:j].mean(),
            })
            i = j
        else:
            i += 1
    return merge_stops(stops)


def merge_stops(stops, max_gap_min=90):
    """Join back-to-back stops at the same place (GPS jitter can split one long stay)."""
    merged = []
    for s in stops:
        if merged:
            m = merged[-1]
            gap = (s["start"] - m["end"]).total_seconds() / 60
            dx, dy = to_xy(s["lat"] - m["lat"], s["lon"] - m["lon"], m["lat"])
            if gap <= max_gap_min and np.hypot(dx, dy) <= STOP_RADIUS_M * 2:
                m["end"] = s["end"]
                m["dur_h"] = (m["end"] - m["start"]).total_seconds() / 3600
                continue
        merged.append(dict(s))
    return merged


def main():
    gps = pd.read_excel(GPS_FILE).rename(columns={v: k for k, v in GPS_COLS.items()})
    gps["timestamp"] = pd.to_datetime(gps["timestamp"])
    gps = gps.dropna(subset=["lat", "lon", "timestamp"])
    gps = gps[gps.lat.between(-90, 90) & gps.lon.between(-180, 180)]
    gps = gps.sort_values(["vehicle_code", "timestamp"])
    print(f"GPS rows: {len(gps):,} | vehicles: {gps.vehicle_code.nunique()}")

    stops = []
    for _, g in gps.groupby("vehicle_code"):
        stops += detect_stops(g)
    stops = pd.DataFrame(stops)
    if stops.empty:
        print("No stops found. Try lowering STOP_MIN_MIN or raising STOP_RADIUS_M.")
        return
    print(f"Stops detected: {len(stops):,}")

    # cluster stop locations (haversine DBSCAN, eps in radians)
    eps = CLUSTER_EPS_M / 6371000.0
    coords = np.radians(stops[["lat", "lon"]].values)
    stops["cluster"] = DBSCAN(eps=eps, min_samples=MIN_STOPS, metric="haversine",
                              algorithm="ball_tree").fit_predict(coords)
    stops = stops[stops.cluster >= 0]
    if stops.empty:
        print("No clusters. Try lowering MIN_STOPS or raising CLUSTER_EPS_M.")
        return

    rows = []
    for c, s in stops.groupby("cluster"):
        lat0, lon0 = s.lat.mean(), s.lon.mean()
        x, y = to_xy(s.lat.values, s.lon.values, lat0)
        cx, cy = to_xy(lat0, lon0, lat0)
        d = np.hypot(x - cx, y - cy)
        radius = max(MIN_RADIUS_M, int(np.ceil((np.percentile(d, 90) + STOP_RADIUS_M) / 10) * 10))
        long_share = (s.dur_h >= LONG_STAY_HOURS).mean()
        rows.append({
            "project_code": "",
            "project_name": "",
            "lat": round(lat0, 6),
            "lon": round(lon0, 6),
            "radius_m": radius,
            "stops": len(s),
            "vehicles": s.vehicle_code.nunique(),
            "avg_stay_h": round(s.dur_h.mean(), 2),
            "long_stay_pct": round(long_share * 100),
            "first_seen": s.start.min(),
            "last_seen": s.end.max(),
            "hint": ("probably depot/parking/home (many overnight stays)" if long_share >= 0.3
                     else "possible project/work site"),
            "map_link": f"https://www.google.com/maps?q={lat0:.6f},{lon0:.6f}",
        })
    out = pd.DataFrame(rows).sort_values("stops", ascending=False).reset_index(drop=True)
    out["project_code"] = [f"S{i + 1:03d}" for i in range(len(out))]
    out.to_excel(OUT_FILE, index=False)
    print(f"Candidate sites: {len(out)} -> saved to {OUT_FILE}")
    print(out[["project_code", "stops", "vehicles", "avg_stay_h", "hint"]].head(15).to_string(index=False))


if __name__ == "__main__":
    main()
