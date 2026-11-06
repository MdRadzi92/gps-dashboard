"""
Step 4: Upload visits_result.xlsx (sheet "Visits") to a Lark Base table.
- New visits are created, visits already in the table (same visit_id) are updated.
- Safe to run every day: no duplicates.

Settings are read from lark.env (see lark.env.example).
Test without internet/Lark:  python upload_to_lark.py --dry-run
"""
import os
import sys
import time

import pandas as pd
import requests


def load_env(path="lark.env"):
    if os.path.exists(path):
        for line in open(path, encoding="utf-8"):
            line = line.strip()
            if line and not line.startswith("#") and "=" in line:
                k, v = line.split("=", 1)
                os.environ.setdefault(k.strip(), v.strip())


load_env()
DOMAIN = os.environ.get("LARK_DOMAIN", "https://open.larksuite.com")  # Feishu China: https://open.feishu.cn
APP_ID = os.environ.get("LARK_APP_ID", "")
APP_SECRET = os.environ.get("LARK_APP_SECRET", "")
APP_TOKEN = os.environ.get("LARK_APP_TOKEN", "")   # Base id, from the Base URL
TABLE_ID = os.environ.get("LARK_TABLE_ID", "")     # starts with "tbl"
TZ = os.environ.get("LOCAL_TZ", "Asia/Kuala_Lumpur")
VISITS_FILE = "visits_result.xlsx"
BATCH = 500
DRY = "--dry-run" in sys.argv


def call(method, path, token=None, **kw):
    headers = {"Authorization": f"Bearer {token}"} if token else {}
    r = requests.request(method, DOMAIN + path, headers=headers, timeout=60, **kw)
    r.raise_for_status()
    data = r.json()
    if data.get("code") != 0:
        raise RuntimeError(f"Lark API error {data.get('code')}: {data.get('msg')}")
    time.sleep(0.3)  # stay under rate limits
    return data["data"] if "data" in data else data


def get_token():
    r = requests.post(DOMAIN + "/open-apis/auth/v3/tenant_access_token/internal",
                      json={"app_id": APP_ID, "app_secret": APP_SECRET}, timeout=30)
    r.raise_for_status()
    d = r.json()
    if d.get("code") != 0:
        raise RuntimeError(f"Token error: {d.get('msg')}")
    return d["tenant_access_token"]


def text_of(v):
    """Lark may return text as a string or a list of segments."""
    if isinstance(v, list):
        return "".join(seg.get("text", "") for seg in v if isinstance(seg, dict))
    return str(v) if v is not None else ""


def existing_ids(token):
    """visit_id -> record_id for every row already in the table."""
    out, page = {}, None
    base = f"/open-apis/bitable/v1/apps/{APP_TOKEN}/tables/{TABLE_ID}/records/search"
    while True:
        params = {"page_size": 500}
        if page:
            params["page_token"] = page
        d = call("POST", base, token, params=params, json={"field_names": ["visit_id"]})
        for it in d.get("items", []):
            out[text_of(it["fields"].get("visit_id"))] = it["record_id"]
        if not d.get("has_more"):
            return out
        page = d["page_token"]


def to_ms(ts):
    return int(pd.Timestamp(ts).tz_localize(TZ).tz_convert("UTC").timestamp() * 1000)


def to_fields(r):
    return {
        "visit_id": str(r.visit_id),
        "vehicle_code": str(r.vehicle_code),
        "device_id": "" if pd.isna(r.device_id) else str(r.device_id),
        "project_code": str(r.project_code),
        "project_name": "" if pd.isna(r.project_name) else str(r.project_name),
        "month": str(r.month),
        "enter": to_ms(r.enter),
        "exit": to_ms(r.exit),
        "dwell_min": float(r.dwell_min),
        "points": int(r.points),
        "lat": float(r.lat),
        "lon": float(r.lon),
    }


def chunks(lst, n):
    for i in range(0, len(lst), n):
        yield lst[i:i + n]


def main():
    visits = pd.read_excel(VISITS_FILE, sheet_name="Visits")
    print(f"Visits to sync: {len(visits)}")
    if visits.empty:
        return

    if DRY:
        print("[dry-run] example payload:", to_fields(next(visits.itertuples())))
        return

    missing = [k for k, v in {"LARK_APP_ID": APP_ID, "LARK_APP_SECRET": APP_SECRET,
                              "LARK_APP_TOKEN": APP_TOKEN, "LARK_TABLE_ID": TABLE_ID}.items() if not v]
    if missing:
        sys.exit(f"ERROR: missing settings in lark.env: {', '.join(missing)}")

    token = get_token()
    have = existing_ids(token)
    print(f"Rows already in Lark: {len(have)}")

    create, update = [], []
    for r in visits.itertuples():
        f = to_fields(r)
        if f["visit_id"] in have:
            update.append({"record_id": have[f["visit_id"]], "fields": f})
        else:
            create.append({"fields": f})

    base = f"/open-apis/bitable/v1/apps/{APP_TOKEN}/tables/{TABLE_ID}/records"
    for part in chunks(create, BATCH):
        call("POST", base + "/batch_create", token, json={"records": part})
    for part in chunks(update, BATCH):
        call("POST", base + "/batch_update", token, json={"records": part})
    print(f"Created {len(create)}, updated {len(update)}")


if __name__ == "__main__":
    main()
