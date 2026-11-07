"""Training Dashboard - local sync server.

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

FROZEN = getattr(sys, "frozen", False)  # running as the downloadable app (PyInstaller)
ROOT = Path(getattr(sys, "_MEIPASS", "")) if FROZEN else Path(__file__).resolve().parent.parent
WEB = ROOT / "web"
# The downloadable app keeps your data in a folder in your home directory; from source, next to the code.
HOME_DIR = Path.home() / "TrainingDashboard"
if not HOME_DIR.exists() and (Path.home() / "T100Dashboard").exists():  # keep data from earlier versions
    HOME_DIR = Path.home() / "T100Dashboard"
DATA = Path(os.getenv("T100_DATA_DIR", HOME_DIR / "data" if FROZEN else ROOT / "data")).expanduser()
TOKENS = Path(os.getenv("GARMINTOKENS", HOME_DIR / ".garminconnect" if FROZEN else ROOT / ".garminconnect")).expanduser()
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
            how = ("Close the Training Dashboard window and start it again with --login, or delete the "
                   f"{TOKENS} folder and start it again." if FROZEN else
                   "Run `python server/app.py --login` once, or set GARMIN_EMAIL and GARMIN_PASSWORD.")
            raise RuntimeError(f"Not signed in to Garmin. {how}") from e
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


COACHED = ("race", "phases")  # what a coach's shared plan can set
COACH_SECONDS = int(os.getenv("T100_COACH_SECONDS", "600"))


def _clean(name: str, rows: Any) -> list[dict[str, str]]:
    cols = STORES[name]
    if not isinstance(rows, list):
        return []
    return [{c: ("" if r.get(c) is None else str(r.get(c))[:2000]) for c in cols} for r in rows[:5000] if isinstance(r, dict)]


def _write_json(p: Path, value: Any) -> None:
    with _store_lock:
        DATA.mkdir(parents=True, exist_ok=True)
        tmp = p.with_suffix(".tmp")
        tmp.write_text(json.dumps(value, indent=1, ensure_ascii=False), "utf-8")
        tmp.replace(p)


def settings() -> dict[str, Any]:
    p = DATA / "settings.json"
    try:
        return json.loads(p.read_text("utf-8")) if p.exists() else {}
    except ValueError:
        return {}


def _fetch_json(url: str, timeout: int = 10) -> Any:
    import urllib.request

    req = urllib.request.Request(url, headers={"User-Agent": "training-dashboard", "Accept": "application/json"})
    with urllib.request.urlopen(req, timeout=timeout) as r:  # noqa: S310 - https only, checked below
        return json.loads(r.read(2_000_000).decode("utf-8"))


_coach: dict[str, Any] = {"at": 0.0, "url": "", "plan": None, "error": None}
_coach_lock = threading.Lock()


def coach_plan(force: bool = False) -> dict[str, Any] | None:
    """Your coach's shared plan (race and phases), re-read every 10 minutes."""
    url = (settings().get("coach_url") or "").strip()
    if not url:
        return None
    with _coach_lock:
        fresh = _coach["url"] == url and time.time() - _coach["at"] < COACH_SECONDS
        if fresh and not force:
            return _coach["plan"]
        try:
            raw = _fetch_json(url)
            if not isinstance(raw, dict):
                raise ValueError("The plan file isn't in the right format.")
            plan = {k: _clean(k, raw.get(k)) for k in COACHED if k in raw}
            plan["message"] = str(raw.get("message") or "")[:500]
            plan["coach"] = str(raw.get("coach") or "")[:120]
            plan["updated"] = str(raw.get("updated") or "")[:40]
            _coach.update(at=time.time(), url=url, plan=plan, error=None)
        except Exception as e:  # keep the last good copy if the link is briefly unreachable
            log.warning("Couldn't read the coach plan: %s", e)
            _coach.update(at=time.time(), url=url, error=str(e))
            if _coach.get("plan") is None or _coach["url"] != url:
                _coach["plan"] = None
        return _coach["plan"]


@app.get("/api/store/<name>")
@needs_token
def get_store(name):
    p = store_path(name)
    if name in COACHED:
        plan = coach_plan()
        if plan and name in plan:
            return table(STORES[name], plan[name], source="coach", coach=plan.get("coach"), updated=plan.get("updated"))
    example = ROOT / "data" / f"{name}.example.json"
    src = p if p.exists() else example if example.exists() else None
    rows = json.loads(src.read_text("utf-8")) if src else []
    return table(STORES[name], rows, source="local")


@app.put("/api/store/<name>")
@needs_token
def put_store(name):
    p = store_path(name)
    if name in COACHED and (coach_plan() or {}).get(name) is not None:
        return jsonify({"error": "Your coach manages this. Remove the coach plan link in Settings to edit it yourself."}), 409
    body = request.get_json(force=True, silent=False)
    rows = body.get("rows") if isinstance(body, dict) else body
    if not isinstance(rows, list) or len(rows) > 5000:
        abort(400)
    clean = _clean(name, rows)
    _write_json(p, clean)
    return table(STORES[name], clean, source="local")


@app.get("/api/settings")
@needs_token
def get_settings():
    s = settings()
    plan = coach_plan() if s.get("coach_url") else None
    return jsonify({"coach_url": s.get("coach_url", ""), "coach": (plan or {}).get("coach", ""),
                    "coach_message": (plan or {}).get("message", ""), "coach_updated": (plan or {}).get("updated", ""),
                    "coach_error": _coach.get("error") if s.get("coach_url") else None})


@app.put("/api/settings")
@needs_token
def put_settings():
    body = request.get_json(force=True) or {}
    s = settings()
    if "coach_url" in body:
        url = str(body.get("coach_url") or "").strip()
        if url and not url.startswith("https://"):
            return jsonify({"error": "The coach plan link must start with https://"}), 400
        if url:
            try:
                raw = _fetch_json(url)
                if not isinstance(raw, dict) or not any(k in raw for k in COACHED):
                    raise ValueError("That link doesn't contain a training plan.")
            except Exception as e:
                return jsonify({"error": f"Couldn't read that link: {e}"}), 400
        s["coach_url"] = url
    _write_json(DATA / "settings.json", s)
    with _coach_lock:
        _coach.update(at=0.0, url="", plan=None, error=None)
    return get_settings()


@app.get("/api/export-plan")
@needs_token
def export_plan():
    """Your race and phases as a plan file to share with the people you coach."""
    def rows(name):
        p = store_path(name)
        example = ROOT / "data" / f"{name}.example.json"
        src = p if p.exists() else example if example.exists() else None
        return json.loads(src.read_text("utf-8")) if src else []

    plan = {"t100_plan": 1, "coach": request.args.get("coach", "")[:120], "message": request.args.get("message", "")[:500],
            "updated": dt.datetime.now().isoformat(timespec="minutes"), "race": rows("race"), "phases": rows("phases")}
    res = app.response_class(json.dumps(plan, indent=1, ensure_ascii=False), mimetype="application/json")
    res.headers["Content-Disposition"] = "attachment; filename=training-plan.json"
    return res


# --------------------------------------------------------------------------
# App updates
# --------------------------------------------------------------------------
@app.get("/api/version")
def version():
    try:
        from version import REPO, VERSION
    except ImportError:
        REPO, VERSION = "", "dev"
    info = {"version": VERSION, "repo": REPO, "latest": None, "url": None, "update": False}
    if REPO and VERSION != "dev":
        def fetch():
            r = _fetch_json(f"https://api.github.com/repos/{REPO}/releases/latest")
            return {"latest": r.get("tag_name"), "url": r.get("html_url")}
        try:
            latest = cached("version", fetch)
            info.update(latest)
            info["update"] = bool(latest.get("latest")) and latest["latest"].lstrip("v") != VERSION.lstrip("v")
        except Exception as e:
            log.info("Update check failed: %s", e)
    return jsonify(info)


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
    ap = argparse.ArgumentParser(description="Training Dashboard server")
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
    print(f"Training Dashboard running at http://{args.host}:{args.port}")
    app.run(host=args.host, port=args.port, threaded=True)


if __name__ == "__main__":
    main()
