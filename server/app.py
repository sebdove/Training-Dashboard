"""T100 Training Dashboard - local sync server.

Logs in to Garmin Connect with your own account (via the open-source
`garminconnect` library), reshapes the data into the tables the dashboard
draws, and serves the dashboard itself.

Run:
    python server/app.py --login     # first time: sign in and save tokens
    python server/app.py             # start the dashboard on http://127.0.0.1:8100
"""

from __future__ import annotations

import argparse
import datetime as dt
import getpass
import json
import logging
import os
import secrets
import sys
import threading
import time
from functools import wraps
from pathlib import Path
from typing import Any, Callable

from flask import Flask, abort, jsonify, request, send_from_directory

ROOT = Path(__file__).resolve().parent.parent
WEB = ROOT / "web"
DATA = Path(os.getenv("T100_DATA_DIR", ROOT / "data")).expanduser()
TOKENS = Path(os.getenv("GARMINTOKENS", ROOT / ".garminconnect")).expanduser()
CACHE_SECONDS = int(os.getenv("T100_CACHE_SECONDS", "900"))
APP_TOKEN = os.getenv("T100_APP_TOKEN", "")  # optional: require this token when hosted remotely

log = logging.getLogger("t100")
app = Flask(__name__, static_folder=None)

# --------------------------------------------------------------------------
# Garmin client
# --------------------------------------------------------------------------
_client = None
_client_lock = threading.Lock()


def garmin():
    """Return a logged-in Garmin client, using saved tokens."""
    global _client
    with _client_lock:
        if _client is not None:
            return _client
        try:
            from garminconnect import Garmin
        except ImportError as e:  # pragma: no cover
            raise RuntimeError("Install requirements first: pip install -r requirements.txt") from e
        email = os.getenv("GARMIN_EMAIL")
        password = os.getenv("GARMIN_PASSWORD")
        client = Garmin(email, password) if (email and password) else Garmin()
        try:
            client.login(str(TOKENS))
        except Exception as e:
            raise RuntimeError(
                "Not signed in to Garmin. Run `python server/app.py --login` once, "
                "or set GARMIN_EMAIL and GARMIN_PASSWORD."
            ) from e
        _client = client
        return client


def interactive_login() -> None:
    from garminconnect import Garmin

    email = os.getenv("GARMIN_EMAIL") or input("Garmin email: ").strip()
    password = os.getenv("GARMIN_PASSWORD") or getpass.getpass("Garmin password: ")
    client = Garmin(email, password, prompt_mfa=lambda: input("Garmin MFA code: ").strip())
    TOKENS.mkdir(parents=True, exist_ok=True)
    client.login(str(TOKENS))
    try:
        client.client.dump(str(TOKENS))
    except Exception:
        pass
    print(f"Signed in. Tokens saved to {TOKENS}. Your password was not stored.")


# --------------------------------------------------------------------------
# Small helpers
# --------------------------------------------------------------------------
_cache: dict[str, tuple[float, Any]] = {}
_cache_lock = threading.Lock()


def cached(key: str, fn: Callable[[], Any]) -> Any:
    now = time.time()
    with _cache_lock:
        hit = _cache.get(key)
        if hit and now - hit[0] < CACHE_SECONDS:
            return hit[1]
    value = fn()
    with _cache_lock:
        _cache[key] = (now, value)
    return value


def table(columns: list[str], rows: list[dict[str, Any]], **extra: Any):
    return jsonify({"columns": columns, "rows": rows, **extra})


def day(s: str | None, default: dt.date | None = None) -> dt.date:
    if not s:
        return default or dt.date.today()
    return dt.date.fromisoformat(str(s)[:10])


def days(start: dt.date, end: dt.date):
    d = start
    while d <= end:
        yield d
        d += dt.timedelta(days=1)


def num(x: Any) -> float | None:
    try:
        return None if x is None or x == "" else float(x)
    except (TypeError, ValueError):
        return None


def first_device_value(m: Any) -> dict[str, Any]:
    """Garmin keys some training data by device id: pick the primary device's entry."""
    if not isinstance(m, dict) or not m:
        return {}
    for v in m.values():
        if isinstance(v, dict) and v.get("primaryTrainingDevice"):
            return v
    v = next(iter(m.values()))
    return v if isinstance(v, dict) else {}


def needs_token(fn):
    @wraps(fn)
    def wrapper(*a, **k):
        if APP_TOKEN:
            given = request.headers.get("X-App-Token") or request.args.get("token") or ""
            if not secrets.compare_digest(given, APP_TOKEN):
                abort(401)
        return fn(*a, **k)

    return wrapper


@app.errorhandler(Exception)
def on_error(e):
    code = getattr(e, "code", 500)
    if not isinstance(code, int):
        code = 500
    log.warning("Request failed: %s", e)
    return jsonify({"error": str(e) or e.__class__.__name__}), code


# --------------------------------------------------------------------------
# Garmin endpoints, shaped like the dashboard's tables
# --------------------------------------------------------------------------
ACT_COLS = ["id", "name", "type", "start_time", "distance_meters", "duration_seconds", "avg_hr_bpm", "max_hr_bpm", "calories"]


def _activities(start: dt.date, end: dt.date) -> list[dict[str, Any]]:
    return cached(f"act:{start}:{end}", lambda: garmin().get_activities_by_date(start.isoformat(), end.isoformat()) or [])


@app.get("/api/activities")
@needs_token
def activities():
    end = day(request.args.get("end"))
    start = day(request.args.get("start"), end - dt.timedelta(weeks=16))
    rows = []
    for a in _activities(start, end):
        rows.append({
            "id": str(a.get("activityId")),
            "name": a.get("activityName") or "",
            "type": (a.get("activityType") or {}).get("typeKey") or "",
            "start_time": a.get("startTimeLocal") or "",
            "distance_meters": num(a.get("distance")) or 0.0,
            "duration_seconds": num(a.get("duration")) or 0.0,
            "avg_hr_bpm": num(a.get("averageHR")),
            "max_hr_bpm": num(a.get("maxHR")),
            "calories": num(a.get("calories")),
        })
    return table(ACT_COLS, rows)


@app.get("/api/effect")
@needs_token
def effect():
    limit = min(int(request.args.get("limit", 15)), 50)
    end = dt.date.today()
    acts = [a for a in _activities(end - dt.timedelta(days=60), end) if (num(a.get("duration")) or 0) > 0][:limit]
    rows = []
    for a in acts:
        aer, ana, load = num(a.get("aerobicTrainingEffect")), num(a.get("anaerobicTrainingEffect")), num(a.get("activityTrainingLoad"))
        rows.append({
            "id": str(a.get("activityId")), "start_time": a.get("startTimeLocal") or "",
            "type": (a.get("activityType") or {}).get("typeKey") or "", "name": a.get("activityName") or "",
            "aerobic": None if aer is None else round(aer, 1), "anaerobic": None if ana is None else round(ana, 1),
            "label": a.get("trainingEffectLabel"), "load": None if load is None else round(load),
        })
    return table(["id", "start_time", "type", "name", "aerobic", "anaerobic", "label", "load"], rows)


@app.get("/api/vo2")
@needs_token
def vo2():
    end = day(request.args.get("end"))
    start = day(request.args.get("start"), end - dt.timedelta(days=89))

    def fetch():
        raw = garmin().get_max_metrics_range(start.isoformat(), end.isoformat()) or []
        out = {}
        for r in raw if isinstance(raw, list) else [raw]:
            g = (r or {}).get("generic") or {}
            v = num(g.get("vo2MaxPreciseValue")) or num(g.get("vo2MaxValue"))
            if g.get("calendarDate") and v:
                out[g["calendarDate"][:10]] = round(v, 1)
        rows, last = [], None
        for d in days(start, end):  # carry the last value forward, as Garmin Connect's chart does
            last = out.get(d.isoformat(), last)
            if last is not None:
                rows.append({"date": d.isoformat(), "vo2_max": last})
        return rows

    return table(["date", "vo2_max"], cached(f"vo2:{start}:{end}", fetch))


@app.get("/api/hrv")
@needs_token
def hrv():
    end = day(request.args.get("end"))
    start = day(request.args.get("start"), end - dt.timedelta(days=29))

    def fetch():
        raw = garmin().get_hrv_data_range(start.isoformat(), end.isoformat()) or {}
        rows = []
        for s in raw.get("hrvSummaries") or []:
            rows.append({
                "date": (s.get("calendarDate") or "")[:10],
                "last_night_avg_hrv_ms": num(s.get("lastNightAvg")),
                "weekly_avg_hrv_ms": num(s.get("weeklyAvg")),
                "status": s.get("status"),
            })
        return sorted(rows, key=lambda r: r["date"])

    return table(["date", "last_night_avg_hrv_ms", "weekly_avg_hrv_ms", "status"], cached(f"hrv:{start}:{end}", fetch))


@app.get("/api/sleep")
@needs_token
def sleep():
    end = day(request.args.get("end"))
    start = day(request.args.get("start"), end - dt.timedelta(days=29))
    rows = []
    for d in days(start, end):
        raw = cached(f"sleep:{d}", lambda d=d: garmin().get_sleep_data(d.isoformat()) or {})
        s = raw.get("dailySleepDTO") or {}
        secs = num(s.get("sleepTimeSeconds"))
        if not secs:
            continue
        score = ((s.get("sleepScores") or {}).get("overall") or {})
        total = secs or 1
        rows.append({
            "date": d.isoformat(), "sleep_hours": round(secs / 3600, 2),
            "sleep_score": num(score.get("value")), "sleep_score_qualifier": score.get("qualifierKey"),
            "deep_sleep_percent": round(100 * (num(s.get("deepSleepSeconds")) or 0) / total, 1),
            "rem_sleep_percent": round(100 * (num(s.get("remSleepSeconds")) or 0) / total, 1),
        })
    return table(["date", "sleep_hours", "sleep_score", "sleep_score_qualifier", "deep_sleep_percent", "rem_sleep_percent"], rows)


@app.get("/api/rhr")
@needs_token
def rhr():
    end = day(request.args.get("end"))
    n = min(int(request.args.get("days", 30)), 90)
    rows = []
    for d in days(end - dt.timedelta(days=n - 1), end):
        raw = cached(f"rhr:{d}", lambda d=d: garmin().get_rhr_day(d.isoformat()) or {})
        m = (((raw.get("allMetrics") or {}).get("metricsMap") or {}).get("WELLNESS_RESTING_HEART_RATE") or [])
        for r in m:
            v = num(r.get("value"))
            if v is not None:
                rows.append({"date": (r.get("calendarDate") or d.isoformat())[:10], "rhr": v})
    return table(["date", "rhr"], sorted(rows, key=lambda r: r["date"]))


def _status(d: dt.date) -> dict[str, Any]:
    return cached(f"status:{d}", lambda: garmin().get_training_status(d.isoformat()) or {})


@app.get("/api/load")
@needs_token
def load():
    end = day(request.args.get("end"))
    start = day(request.args.get("start"), end - dt.timedelta(days=29))
    rows = []
    for d in days(start, end):
        st = first_device_value(((_status(d).get("mostRecentTrainingStatus") or {}).get("latestTrainingStatusData")))
        a = st.get("acuteTrainingLoadDTO") or {}
        if not a:
            continue
        rows.append({
            "date": d.isoformat(), "atl": num(a.get("dailyTrainingLoadAcute")), "ctl": num(a.get("dailyTrainingLoadChronic")),
            "acwr": num(a.get("dailyAcuteChronicWorkloadRatio")), "acwr_status": a.get("acwrStatus"),
            "training_status": st.get("trainingStatusFeedbackPhrase") or st.get("trainingStatus"),
            "opt_min": num(a.get("minTrainingLoadChronic")), "opt_max": num(a.get("maxTrainingLoadChronic")),
        })
    return table(["date", "atl", "ctl", "acwr", "acwr_status", "training_status", "opt_min", "opt_max"], rows)


@app.get("/api/balance")
@needs_token
def balance():
    d = day(request.args.get("date"))
    cols = ["band", "load", "target_min", "target_max", "status", "feedback", "date"]
    for when in (d, d - dt.timedelta(days=1)):
        b = first_device_value(((_status(when).get("mostRecentTrainingLoadBalance") or {}).get("metricsTrainingLoadBalanceDTOMap")))
        if not b:
            continue

        def band(name, load, lo, hi):
            load, lo, hi = num(load), num(lo), num(hi)
            status = "within" if lo is None or hi is None or load is None else ("below" if load < lo else "above" if load > hi else "within")
            return {"band": name, "load": load, "target_min": lo, "target_max": hi, "status": status,
                    "feedback": b.get("trainingBalanceFeedbackPhrase"), "date": when.isoformat()}

        return table(cols, [
            band("Aerobic low", b.get("monthlyLoadAerobicLow"), b.get("monthlyLoadAerobicLowTargetMin"), b.get("monthlyLoadAerobicLowTargetMax")),
            band("Aerobic high", b.get("monthlyLoadAerobicHigh"), b.get("monthlyLoadAerobicHighTargetMin"), b.get("monthlyLoadAerobicHighTargetMax")),
            band("Anaerobic", b.get("monthlyLoadAnaerobic"), b.get("monthlyLoadAnaerobicTargetMin"), b.get("monthlyLoadAnaerobicTargetMax")),
        ])
    return table(cols, [])


@app.get("/api/scheduled")
@needs_token
def scheduled():
    start = day(request.args.get("start"))
    end = day(request.args.get("end"), start + dt.timedelta(days=7))
    months = sorted({(d.year, d.month) for d in days(start, end)})
    rows = []
    for y, m in months:
        raw = cached(f"sched:{y}:{m}", lambda y=y, m=m: garmin().get_scheduled_workouts(y, m) or {})
        for it in raw.get("calendarItems") or []:
            if it.get("itemType") not in ("workout", "fbtAdaptiveWorkout"):
                continue
            d = (it.get("date") or "")[:10]
            if d and start.isoformat() <= d <= end.isoformat():
                rows.append({"key": f"{d}|{it.get('id')}", "date": d, "sport": it.get("sportTypeKey") or "", "name": it.get("title") or ""})
    return table(["key", "date", "sport", "name"], rows)


@app.get("/api/ftp")
@needs_token
def ftp():
    def fetch():
        raw = garmin().get_cycling_ftp()
        r = raw[0] if isinstance(raw, list) and raw else raw or {}
        watts = num(r.get("functionalThresholdPower")) or num(r.get("value"))
        if not watts:
            return []
        date = str(r.get("calendarDate") or r.get("updatedDate") or "")[:10]
        stale = bool(r.get("isStale")) or (bool(date) and (dt.date.today() - dt.date.fromisoformat(date)).days > 180)
        return [{"date": date, "ftp": watts, "stale": stale}]

    return table(["date", "ftp", "stale"], cached("ftp", fetch))


@app.get("/api/devices")
@needs_token
def devices():
    rows = [{"device_id": str(d.get("deviceId") or ""), "device_name": d.get("productDisplayName") or d.get("displayName") or "",
             "model": d.get("partNumber") or ""} for d in cached("devices", lambda: garmin().get_devices() or [])]
    return table(["device_id", "device_name", "model"], rows)


@app.post("/api/refresh")
@needs_token
def refresh():
    with _cache_lock:
        _cache.clear()
    return jsonify({"ok": True})


# --------------------------------------------------------------------------
# Your own data: race, phases, device log, FTP tests (JSON files in data/)
# --------------------------------------------------------------------------
STORES = {
    "race": ["Race", "Date", "Swim km", "Bike km", "Run km"],
    "phases": ["Phase", "Start", "End", "Colour", "Focus", "Status"],
    "device_log": ["Entry", "Date", "Device", "Category", "Session", "Metric", "Value", "Unit", "Notes"],
    "ftp_tests": ["Date", "FTP (W)", "Weight (kg)", "Source", "Notes"],
}
_store_lock = threading.Lock()


def store_path(name: str) -> Path:
    if name not in STORES:
        abort(404)
    return DATA / f"{name}.json"


@app.get("/api/store/<name>")
@needs_token
def get_store(name):
    p = store_path(name)
    example = ROOT / "data" / f"{name}.example.json"
    src = p if p.exists() else example if example.exists() else None
    rows = json.loads(src.read_text("utf-8")) if src else []
    return table(STORES[name], rows)


@app.put("/api/store/<name>")
@needs_token
def put_store(name):
    p = store_path(name)
    body = request.get_json(force=True, silent=False)
    rows = body.get("rows") if isinstance(body, dict) else body
    if not isinstance(rows, list) or len(rows) > 5000:
        abort(400)
    cols = STORES[name]
    clean = [{c: ("" if r.get(c) is None else str(r.get(c))[:2000]) for c in cols} for r in rows if isinstance(r, dict)]
    with _store_lock:
        DATA.mkdir(parents=True, exist_ok=True)
        tmp = p.with_suffix(".tmp")
        tmp.write_text(json.dumps(clean, indent=1, ensure_ascii=False), "utf-8")
        tmp.replace(p)
    return table(cols, clean)


# --------------------------------------------------------------------------
# The dashboard itself
# --------------------------------------------------------------------------
@app.get("/")
def index():
    return send_from_directory(WEB, "index.html")


@app.get("/<path:path>")
def static_files(path):
    if path.startswith("api/"):
        abort(404)
    return send_from_directory(WEB, path)


def main() -> None:
    ap = argparse.ArgumentParser(description="T100 Training Dashboard server")
    ap.add_argument("--login", action="store_true", help="sign in to Garmin and save tokens, then exit")
    ap.add_argument("--host", default=os.getenv("T100_HOST", "127.0.0.1"))
    ap.add_argument("--port", type=int, default=int(os.getenv("T100_PORT", "8100")))
    args = ap.parse_args()
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    if args.login:
        interactive_login()
        return
    if args.host not in ("127.0.0.1", "localhost") and not APP_TOKEN:
        print("Refusing to listen beyond this computer without T100_APP_TOKEN set (see README).", file=sys.stderr)
        sys.exit(2)
    print(f"T100 dashboard running at http://{args.host}:{args.port}")
    app.run(host=args.host, port=args.port, threaded=True)


if __name__ == "__main__":
    main()
