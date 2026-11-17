"""SmartRail AI - Flask + WebSocket server.

* /ws/device  <- ESP32 (RFID, IR sensors) and -> servo / LCD commands
* /ws/ui      -> live state for the browser control room
* A simulation engine runs the Tamil Nadu corridor (5 tracks); the real rig
  is "Switch 1A": Track 1 (main) <-> Track 3 (loop), driven by the servo.

Run:  python app.py      (then open http://localhost:5000)
"""
import json
import os
import random
import sqlite3
import threading
import time
from datetime import datetime, timedelta
from functools import wraps

from flask import (Flask, jsonify, redirect, render_template, request,
                   session, url_for)
from flask_sock import Sock
from werkzeug.security import check_password_hash, generate_password_hash

BASE = os.path.dirname(os.path.abspath(__file__))
DB_PATH = os.environ.get("DB_PATH", os.path.join(BASE, "smartrail.db"))
DEVICE_TOKEN = os.environ.get("DEVICE_TOKEN", "smartrail-device")
SEED_EMAIL = os.environ.get("SEED_EMAIL", "controller@smartrail.gov.in")
SEED_PASSWORD = os.environ.get("SEED_PASSWORD", "controller123")

app = Flask(__name__)
app.secret_key = os.environ.get("SECRET_KEY", "dev-change-me")
sock = Sock(app)
lock = threading.RLock()

CATEGORIES = ("EXPRESS", "PASSENGER", "GOODS", "FREIGHT")
PRIORITY = {"EXPRESS": 100, "PASSENGER": 60, "GOODS": 35, "FREIGHT": 25}
TRACKS = {  # id: (name, direction, speed limit km/h)
    1: ("Up Main Line", "UP", 110), 2: ("Down Main Line", "DOWN", 110),
    3: ("Platform Loop 1", "UP", 65), 4: ("Platform Loop 2", "DOWN", 65),
    5: ("Freight Bypass Siding", "BIDIRECTIONAL", 50)}
STATIONS = [  # code, name, division, platforms
    ("MAS", "Puratchi Thalaivar Dr. MGR Chennai Central", "Chennai Division (MAS)", 12),
    ("MS", "Chennai Egmore", "Chennai Division (MAS)", 11),
    ("TBM", "Tambaram", "Chennai Division (MAS)", 6),
    ("CGL", "Chengalpattu Junction", "Chennai Division (MAS)", 5),
    ("AJJ", "Arakkonam Junction", "Chennai Division (MAS)", 8),
    ("KPD", "Katpadi Junction", "Chennai Division (MAS)", 7),
    ("SA", "Salem Junction", "Salem Division (SA)", 6),
    ("ED", "Erode Junction", "Salem Division (SA)", 5),
    ("CBE", "Coimbatore Junction", "Salem Division (SA)", 6),
    ("TPJ", "Tiruchirappalli Junction", "Tiruchirappalli Division (TPJ)", 7),
    ("KRR", "Karur Junction", "Tiruchirappalli Division (TPJ)", 4),
    ("MDU", "Madurai Junction", "Madurai Division (MDU)", 6),
]
SEED_TRAINS = [  # rfid uid, number, name, category
    ("DEMO0001", "20607", "MGR Chennai Central - Mysuru Vande Bharat Express", "EXPRESS"),
    ("DEMO0002", "12675", "Kovai Superfast Express", "EXPRESS"),
    ("DEMO0003", "16127", "Guruvayur Express", "EXPRESS"),
    ("DEMO0004", "12637", "Pandian Superfast Express", "EXPRESS"),
    ("DEMO0005", "56841", "Karur Passenger", "PASSENGER"),
    ("DEMO0006", "G-7821", "Ennore Thermal Coal Bulk Cargo", "GOODS"),
    ("DEMO0007", "G-3180", "Chennai Port Auto Logistics Cargo", "GOODS"),
    ("DEMO0008", "F-9102", "Salem Steel Plant Heavy BRC Freight", "FREIGHT"),
]


# ------------------------------------------------------------------ database
def db():
    con = sqlite3.connect(DB_PATH, timeout=10)
    con.row_factory = sqlite3.Row
    return con


def init_db():
    con = db()
    con.executescript("""
    CREATE TABLE IF NOT EXISTS users(
        id INTEGER PRIMARY KEY, name TEXT, email TEXT UNIQUE, pw_hash TEXT);
    CREATE TABLE IF NOT EXISTS trains(
        uid TEXT PRIMARY KEY, name TEXT, number TEXT, type TEXT);
    CREATE TABLE IF NOT EXISTS movements(
        id INTEGER PRIMARY KEY, train_uid TEXT, train_name TEXT, train_type TEXT,
        route TEXT, entry_ts REAL, exit_ts REAL, transit_s REAL);
    CREATE TABLE IF NOT EXISTS events(
        id INTEGER PRIMARY KEY, ts REAL, kind TEXT, msg TEXT);
    CREATE TABLE IF NOT EXISTS alerts(
        id INTEGER PRIMARY KEY, ts REAL, winner TEXT, loser TEXT, kind TEXT, track INTEGER,
        action TEXT, plan TEXT, status TEXT, detail TEXT, loser_id TEXT);
    CREATE TABLE IF NOT EXISTS schedules(
        id INTEGER PRIMARY KEY, number TEXT, name TEXT, code TEXT, station TEXT,
        arr TEXT, dep TEXT, platform INTEGER, seq INTEGER, halt INTEGER);
    """)
    if not con.execute("SELECT 1 FROM users WHERE email=?", (SEED_EMAIL,)).fetchone():
        con.execute("INSERT INTO users(name,email,pw_hash) VALUES(?,?,?)",
                    ("Chief Dispatcher", SEED_EMAIL,
                     generate_password_hash(SEED_PASSWORD, method="pbkdf2:sha256")))
    if not con.execute("SELECT 1 FROM trains").fetchone():
        con.executemany("INSERT INTO trains VALUES(?,?,?,?)",
                        [(u, n, no, c) for u, no, n, c in SEED_TRAINS])
    if not con.execute("SELECT 1 FROM schedules").fetchone():
        names = {no: n for _, no, n, _ in SEED_TRAINS}
        routes = {"12637": ["MS", "TBM", "CGL", "MDU"], "20607": ["MAS", "AJJ", "KPD"],
                  "12675": ["MAS", "AJJ", "SA", "CBE"], "16127": ["MS", "TBM", "SA", "ED"],
                  "56841": ["SA", "ED", "KRR"]}
        sname = {s[0]: s[1] for s in STATIONS}
        for no, codes in routes.items():
            t = datetime(2026, 11, 17, random.randint(5, 21), random.choice([0, 10, 40]))
            for i, code in enumerate(codes, 1):
                halt = 5 if i == 1 or i == len(codes) else 2
                con.execute("INSERT INTO schedules(number,name,code,station,arr,dep,platform,seq,halt)"
                            " VALUES(?,?,?,?,?,?,?,?,?)",
                            (no, names.get(no, no), code, sname[code], t.strftime("%H:%M"),
                             (t + timedelta(minutes=halt)).strftime("%H:%M"),
                             random.randint(1, 5), i, halt))
                t += timedelta(minutes=random.randint(35, 80))
    con.commit()
    con.close()


# --------------------------------------------------------------------- state
state = {
    "mode": "AUTO",          # AUTO: AI + auto-routing apply themselves; MANUAL: controller approves
    "switch": "MAIN",        # Switch 1A servo: MAIN = Track 1, LOOP = Track 3
    "ir1": False, "ir2": False,
    "occupied": False, "current": None, "pending": None, "last_scan": None,
    "device_online": False,
    "lcd": ["SMARTRAIL AI", "READY"],
    "paused": False, "speed": 1,
}
sim = {"trains": {}, "pairs": {}, "util": {1: 0, 2: 0, 3: 0, 4: 0, 5: 0}}
entry_time = {"ts": None}
devices, ui_clients = set(), set()


def log(kind, msg):
    con = db()
    con.execute("INSERT INTO events(ts,kind,msg) VALUES(?,?,?)", (time.time(), kind, msg))
    con.commit()
    con.close()


def recent_events(n=40):
    con = db()
    rows = con.execute("SELECT ts,kind,msg FROM events ORDER BY id DESC LIMIT ?", (n,)).fetchall()
    con.close()
    return [dict(r) for r in rows]


def open_alerts():
    con = db()
    rows = con.execute("SELECT * FROM alerts WHERE status IN ('PREDICTED','DIVERTED','HELD') "
                       "ORDER BY id DESC LIMIT 5").fetchall()
    con.close()
    return [dict(r) for r in rows]


def train_view(t):
    mult = state["speed"]
    rate = max(0.1, 0.6 * mult * t["speed"] / 100)
    eta_min = int((100 - t["progress"]) / rate)
    eta = (datetime.now() + timedelta(minutes=eta_min)).strftime("%H:%M")
    return dict(t, eta=eta, progress=round(t["progress"], 1))


def kpis():
    ts = list(sim["trains"].values())
    n = len(ts) or 1
    on_time = sum(1 for t in ts if t["delay"] <= 5)
    conflict = any(a["status"] == "PREDICTED" for a in open_alerts())
    return {"active": len(ts), "punctuality": round(100 * on_time / n, 1),
            "avg_delay": round(sum(t["delay"] for t in ts) / n, 1),
            "interlocking": "CONFLICT" if conflict else "NOMINAL"}


def snapshot(full=True):
    s = {"type": "state" if full else "tick", "state": state,
         "trains": [train_view(t) for t in sim["trains"].values()],
         "alerts": open_alerts(), "kpi": kpis(), "now": time.time()}
    if full:
        s["events"] = recent_events()
    return s


def _send(ws, payload):
    try:
        ws.send(json.dumps(payload))
        return True
    except Exception:
        return False


def push_state(full=True):
    snap = snapshot(full)
    for c in list(ui_clients):
        if not _send(c, snap):
            ui_clients.discard(c)


def to_device(payload):
    for d in list(devices):
        if not _send(d, payload):
            devices.discard(d)


def set_lcd(l1, l2):
    state["lcd"] = [l1[:16], l2[:16]]
    to_device({"type": "lcd", "l1": state["lcd"][0], "l2": state["lcd"][1]})


def set_switch(pos, source):
    if pos not in ("MAIN", "LOOP"):
        return
    changed = state["switch"] != pos
    state["switch"] = pos
    to_device({"type": "switch", "pos": pos})
    if changed:
        log("switch", f"Switch 1A -> {pos} ({'Track 3' if pos == 'LOOP' else 'Track 1'}) [{source}]")


def get_train(uid):
    con = db()
    row = con.execute("SELECT * FROM trains WHERE uid=?", (uid,)).fetchone()
    if not row:
        con.execute("INSERT INTO trains VALUES(?,?,?,?)",
                    (uid, f"Unregistered {uid[-4:]}", uid[-4:], "PASSENGER"))
        con.commit()
        row = con.execute("SELECT * FROM trains WHERE uid=?", (uid,)).fetchone()
        log("system", f"New RFID tag {uid} auto-registered")
    con.close()
    return dict(row)


def decide_route(train):
    """Express keeps the main line, goods/freight use the loop, passenger takes
    the main line unless the junction block is occupied."""
    if train["type"] == "EXPRESS":
        return "MAIN"
    if train["type"] in ("GOODS", "FREIGHT"):
        return "LOOP"
    return "LOOP" if state["occupied"] else "MAIN"


# ---------------------------------------------------------------- simulation
def registry():
    con = db()
    rows = [dict(r) for r in con.execute("SELECT * FROM trains")]
    con.close()
    return rows


def new_run(reg, track=None, progress=None):
    cat = reg["type"]
    if track is None:
        track = random.choice([1, 1, 2]) if cat in ("EXPRESS", "PASSENGER") else random.choice([1, 2, 5])
    src, dst = random.sample([s for s in STATIONS], 2)
    limit = TRACKS[track][2]
    cap = limit if cat in ("EXPRESS", "PASSENGER") else min(limit, 70)
    return {"id": reg["uid"], "number": reg["number"], "name": reg["name"], "category": cat,
            "track": track, "from": src[1], "to": dst[1], "real": False,
            "speed": int(cap * random.uniform(0.6, 0.97)),
            "progress": random.uniform(0, 45) if progress is None else progress,
            "delay": random.choice([0, 0, 0, 2, 4, 14, 22]), "status": "MOVING", "hold": 0, "div": 0}


def seed_sim():
    sim["trains"].clear()
    regs = [r for r in registry() if not r["uid"].startswith("RT-")][:8]
    random.shuffle(regs)
    for i, r in enumerate(regs[:6]):
        sim["trains"][r["uid"]] = new_run(r, track=1 if i < 3 else None, progress=8 + i * 9 if i < 3 else None)
    sim["pairs"].clear()


def score(t):
    return int(PRIORITY[t["category"]] * 1.5 + max(0, 40 - t["delay"]) + (20 if t["real"] else 0))


def track_clear(n):
    return not any(t["track"] == n for t in sim["trains"].values())


def raise_conflict(a, b, track):
    win, lose = (a, b) if score(a) >= score(b) else (b, a)
    if track == 1 and track_clear(3):
        plan, action = "DIVERT3", f"Divert #{lose['number']} to Track 3 via Switch 1A"
    elif track == 2 and track_clear(4):
        plan, action = "DIVERT4", f"Divert #{lose['number']} to Track 4 via Switch 2A"
    else:
        plan, action = "HOLD", f"Hold #{lose['number']} at signal (safe spacing)"
    detail = (f"#{win['number']} ({win['name']}) scores {score(win)} pts vs #{lose['number']} "
              f"{score(lose)} pts. {action}.")
    con = db()
    cur = con.execute("INSERT INTO alerts(ts,winner,loser,kind,track,action,plan,status,detail,loser_id)"
                      " VALUES(?,?,?,?,?,?,?,?,?,?)",
                      (time.time(), win["number"], lose["number"], "CONVERGING CONTENTION", track,
                       action, plan, "PREDICTED", detail, lose["id"]))
    con.commit()
    aid = cur.lastrowid
    con.close()
    log("alert", f"Conflict on Track {track}: #{a['number']} / #{b['number']} -> {action}")
    if state["mode"] == "AUTO":
        apply_alert(aid)
    return aid


def apply_alert(aid, approve=True):
    con = db()
    al = con.execute("SELECT * FROM alerts WHERE id=?", (aid,)).fetchone()
    if not al or al["status"] != "PREDICTED":
        con.close()
        return False
    t = sim["trains"].get(al["loser_id"])
    plan = al["plan"] if approve else "HOLD"
    if t:
        if plan == "DIVERT3":
            t["track"], t["status"], t["div"] = 3, "DIVERTED", 25
            set_switch("LOOP", "AI dispatch")
        elif plan == "DIVERT4":
            t["track"], t["status"], t["div"] = 4, "DIVERTED", 25
        else:
            t["status"], t["hold"] = "HOLD", 10
    status = "DIVERTED" if plan.startswith("DIVERT") else "HELD"
    con.execute("UPDATE alerts SET status=? WHERE id=?", (status, aid))
    con.commit()
    con.close()
    log("alert", f"Alert {aid}: {status} ({'approved' if approve else 'rejected -> hold'})")
    return True


def resolve_pairs():
    for key in list(sim["pairs"]):
        a, b = [sim["trains"].get(i) for i in key]
        if not a or not b or a["track"] != b["track"] or abs(a["progress"] - b["progress"]) > 28:
            con = db()
            con.execute("UPDATE alerts SET status='RESOLVED' WHERE id=? AND status!='PREDICTED'",
                        (sim["pairs"][key],))
            con.commit()
            con.close()
            del sim["pairs"][key]


def sim_tick():
    with lock:
        mult = state["speed"]
        for t in list(sim["trains"].values()):
            sim["util"][t["track"]] += 1
            if t["real"]:
                continue
            if t["status"] == "HOLD":
                t["hold"] -= 1
                if t["hold"] <= 0:
                    t["status"] = "MOVING"
                continue
            if t["status"] == "DIVERTED":
                t["div"] -= 1
                if t["div"] <= 0:
                    t["status"] = "MOVING"
            t["progress"] += 0.6 * mult * t["speed"] / 100
            if t["progress"] >= 100:
                reg = {"uid": t["id"], "number": t["number"], "name": t["name"], "type": t["category"]}
                sim["trains"][t["id"]] = new_run(reg, progress=0)
        by_track = {}
        for t in sim["trains"].values():
            by_track.setdefault(t["track"], []).append(t)
        for track, ts in by_track.items():
            ts.sort(key=lambda x: x["progress"])
            for a, b in zip(ts, ts[1:]):
                key = frozenset((a["id"], b["id"]))
                if b["progress"] - a["progress"] < 12 and key not in sim["pairs"]:
                    sim["pairs"][key] = raise_conflict(a, b, track)
        resolve_pairs()
        if (state["mode"] == "AUTO" and state["switch"] == "LOOP" and not state["occupied"]
                and not state["pending"]
                and not any(t["status"] == "DIVERTED" and t["track"] == 3 for t in sim["trains"].values())):
            set_switch("MAIN", "auto-restore")
        push_state(full=False)


def sim_loop():
    while True:
        time.sleep(1)
        if state["paused"] or not (ui_clients or devices):
            continue
        try:
            sim_tick()
        except Exception as e:  # keep the engine alive
            print("sim error:", e)


def trigger_conflict():
    with lock:
        regs = [r for r in registry() if r["type"] == "EXPRESS"][:2] or registry()[:2]
        for i, r in enumerate(regs):
            sim["trains"][r["uid"]] = new_run(r, track=1, progress=20 + i * 4)
        sim["pairs"].clear()
        log("system", "Simulated conflict triggered on Track 1")
        push_state()


# ------------------------------------------------------------ event handling
def handle_device(msg):
    with lock:
        t = msg.get("type")
        if t == "rfid":
            uid = str(msg.get("uid", "")).upper()
            train = get_train(uid)
            state["pending"] = train
            state["last_scan"] = {"uid": uid, "train": train, "ts": time.time()}
            log("rfid", f"RFID {uid}: #{train['number']} {train['name']} ({train['type']})")
            if state["mode"] == "AUTO":
                route = decide_route(train)
                set_switch(route, "auto")
            else:
                route = state["switch"]
            # the physical train appears on the track display
            rid = "RT-" + uid
            sim["trains"].pop(uid, None)
            run = new_run(dict(train, uid=rid), track=1 if route == "MAIN" else 3, progress=3)
            run.update(real=True, speed=40, **{"from": "Rig entry", "to": "Rig exit"})
            sim["trains"][rid] = run
            set_lcd(train["name"], f"ROUTE {route}")
        elif t == "ir":
            sensor, on = int(msg.get("sensor", 0)), bool(msg.get("state"))
            state[f"ir{sensor}"] = on
            if sensor == 1 and on:
                train = state["pending"] or {"uid": "UNKNOWN", "name": "Unknown train",
                                              "type": "UNKNOWN", "number": "?"}
                state["current"] = dict(train, route=state["switch"])
                state["pending"] = None
                state["occupied"] = True
                entry_time["ts"] = time.time()
                rt = sim["trains"].get("RT-" + train["uid"])
                if rt:
                    rt["progress"] = 40
                log("ir", f"IR1: {train['name']} entered the junction block")
                set_lcd("BLOCK OCCUPIED", train["name"])
            elif sensor == 2 and on and state["occupied"]:
                cur, now = state["current"], time.time()
                transit = now - (entry_time["ts"] or now)
                con = db()
                con.execute("INSERT INTO movements(train_uid,train_name,train_type,route,"
                            "entry_ts,exit_ts,transit_s) VALUES(?,?,?,?,?,?,?)",
                            (cur["uid"], cur["name"], cur["type"], cur["route"],
                             entry_time["ts"], now, transit))
                con.commit()
                con.close()
                log("ir", f"IR2: {cur['name']} cleared via {cur['route']} ({transit:.1f}s)")
                sim["trains"].pop("RT-" + cur["uid"], None)
                state["occupied"], state["current"] = False, None
                set_lcd("SECTION CLEAR", "READY")
        elif t == "switch_ack":
            log("system", f"Servo confirmed {msg.get('pos')}")
        elif t == "hello":
            rc = str(msg.get("rc522", "?"))
            ok = rc not in ("0", "00", "ff", "?")
            log("system", f"ESP32 online (fw {msg.get('fw', '?')}) - RC522 "
                          f"{'OK' if ok else 'NOT DETECTED - check SPI wiring'} (version 0x{rc})")
        push_state()


# ------------------------------------------------------------------ websocket
@sock.route("/ws/device")
def ws_device(ws):
    if request.args.get("token") != DEVICE_TOKEN:
        ws.close()
        return
    with lock:
        devices.add(ws)
        state["device_online"] = True
        log("system", "ESP32 connected")
        _send(ws, {"type": "switch", "pos": state["switch"]})
        _send(ws, {"type": "lcd", "l1": state["lcd"][0], "l2": state["lcd"][1]})
        push_state()
    try:
        while True:
            raw = ws.receive()
            if raw is None:
                break
            try:
                handle_device(json.loads(raw))
            except (ValueError, KeyError) as e:
                log("error", f"Bad device message: {e}")
    except Exception:
        pass
    finally:
        with lock:
            devices.discard(ws)
            state["device_online"] = bool(devices)
            log("system", "ESP32 disconnected")
            push_state()


@sock.route("/ws/ui")
def ws_ui(ws):
    if not session.get("uid"):
        ws.close()
        return
    ui_clients.add(ws)
    _send(ws, snapshot())
    try:
        while True:
            if ws.receive() is None:
                break
    except Exception:
        pass
    finally:
        ui_clients.discard(ws)


# ---------------------------------------------------------------------- auth
def login_required(f):
    @wraps(f)
    def wrapper(*a, **k):
        if not session.get("uid"):
            if request.path.startswith("/api/"):
                return jsonify(error="login required"), 401
            return redirect(url_for("login"))
        return f(*a, **k)
    return wrapper


@app.route("/")
def index():
    return redirect(url_for("dashboard" if session.get("uid") else "login"))


@app.route("/login", methods=["GET", "POST"])
def login():
    error = None
    if request.method == "POST":
        con = db()
        u = con.execute("SELECT * FROM users WHERE email=?",
                        (request.form.get("email", "").strip().lower(),)).fetchone()
        con.close()
        if u and check_password_hash(u["pw_hash"], request.form.get("password", "")):
            session["uid"], session["name"] = u["id"], u["name"]
            return redirect(url_for("dashboard"))
        error = "Invalid controller email or password."
    return render_template("login.html", error=error, seed_email=SEED_EMAIL)


@app.route("/signup", methods=["GET", "POST"])
def signup():
    error = None
    if request.method == "POST":
        name = request.form.get("name", "").strip()
        email = request.form.get("email", "").strip().lower()
        pw, pw2 = request.form.get("password", ""), request.form.get("confirm", "")
        if not name or "@" not in email:
            error = "Enter your name and a valid email."
        elif len(pw) < 8:
            error = "Password must be at least 8 characters."
        elif pw != pw2:
            error = "Passwords do not match."
        else:
            try:
                con = db()
                con.execute("INSERT INTO users(name,email,pw_hash) VALUES(?,?,?)",
                            (name, email, generate_password_hash(pw, method="pbkdf2:sha256")))
                con.commit()
                con.close()
                return redirect(url_for("login"))
            except sqlite3.IntegrityError:
                error = "That email is already registered."
    return render_template("signup.html", error=error)


@app.route("/logout")
def logout():
    session.clear()
    return redirect(url_for("login"))


# --------------------------------------------------------------------- pages
@app.route("/dashboard")
@login_required
def dashboard():
    return render_template("app.html", name=session.get("name"))


@app.route("/analytics")
@login_required
def analytics_redirect():
    return redirect(url_for("dashboard") + "#analytics")


# ----------------------------------------------------------------------- API
@app.route("/api/state")
@login_required
def api_state():
    return jsonify(snapshot())


@app.route("/api/meta")
@login_required
def api_meta():
    return jsonify(stations=[dict(code=s[0], name=s[1], division=s[2], platforms=s[3]) for s in STATIONS],
                   tracks=[dict(id=k, name=v[0], direction=v[1], limit=v[2]) for k, v in TRACKS.items()],
                   categories=CATEGORIES, util=sim["util"])


@app.route("/api/switch", methods=["POST"])
@login_required
def api_switch():
    with lock:
        pos = (request.json or {}).get("pos")
        if pos not in ("MAIN", "LOOP"):
            return jsonify(error="pos must be MAIN or LOOP"), 400
        state["mode"] = "MANUAL"
        set_switch(pos, f"manual by {session.get('name')}")
        push_state()
    return jsonify(ok=True)


@app.route("/api/mode", methods=["POST"])
@login_required
def api_mode():
    with lock:
        mode = (request.json or {}).get("mode")
        if mode not in ("AUTO", "MANUAL"):
            return jsonify(error="mode must be AUTO or MANUAL"), 400
        state["mode"] = mode
        log("system", f"Dispatch mode set to {mode}")
        push_state()
    return jsonify(ok=True)


@app.route("/api/sim", methods=["POST"])
@login_required
def api_sim():
    d = request.json or {}
    with lock:
        a = d.get("action")
        if a == "pause":
            state["paused"] = True
        elif a == "resume":
            state["paused"] = False
        elif a == "speed" and d.get("value") in (1, 2, 5):
            state["speed"] = d["value"]
        elif a == "reset":
            seed_sim()
        elif a == "conflict":
            trigger_conflict()
        else:
            return jsonify(error="bad action"), 400
        push_state()
    return jsonify(ok=True)


@app.route("/api/trains", methods=["GET", "POST", "DELETE"])
@login_required
def api_trains():
    con = db()
    if request.method == "POST":
        d = request.json or {}
        ttype = str(d.get("type", "PASSENGER")).upper()
        if not d.get("uid") or ttype not in CATEGORIES:
            con.close()
            return jsonify(error="uid and valid category required"), 400
        con.execute("INSERT OR REPLACE INTO trains VALUES(?,?,?,?)",
                    (str(d["uid"]).upper(), d.get("name", "Train"), d.get("number", "-"), ttype))
        con.commit()
        reg = dict(uid=str(d["uid"]).upper(), name=d.get("name", "Train"),
                   number=d.get("number", "-"), type=ttype)
        with lock:
            sim["trains"][reg["uid"]] = new_run(reg)
    elif request.method == "DELETE":
        uid = str((request.json or {}).get("uid", "")).upper()
        con.execute("DELETE FROM trains WHERE uid=?", (uid,))
        con.commit()
        sim["trains"].pop(uid, None)
    rows = [dict(r) for r in con.execute("SELECT * FROM trains ORDER BY number")]
    con.close()
    return jsonify(rows)


@app.route("/api/schedules", methods=["GET"])
@login_required
def api_schedules():
    con = db()
    rows = [dict(r) for r in con.execute("SELECT * FROM schedules ORDER BY number, seq")]
    con.close()
    return jsonify(rows)


@app.route("/api/schedules/<int:sid>", methods=["PUT"])
@login_required
def api_schedule_edit(sid):
    d = request.json or {}
    con = db()
    con.execute("UPDATE schedules SET arr=?, dep=?, platform=?, halt=? WHERE id=?",
                (d.get("arr"), d.get("dep"), int(d.get("platform", 1)), int(d.get("halt", 2)), sid))
    con.commit()
    con.close()
    return jsonify(ok=True)


@app.route("/api/alerts")
@login_required
def api_alerts():
    con = db()
    rows = [dict(r) for r in con.execute("SELECT * FROM alerts ORDER BY id DESC LIMIT 100")]
    con.close()
    return jsonify(rows)


@app.route("/api/alerts/<int:aid>/decide", methods=["POST"])
@login_required
def api_alert_decide(aid):
    with lock:
        ok = apply_alert(aid, approve=(request.json or {}).get("action") == "approve")
        push_state()
    return jsonify(ok=ok)


@app.route("/api/simulate", methods=["POST"])
@login_required
def api_simulate():
    """Fire the same events the ESP32 would send - demos without hardware."""
    d = request.json or {}
    if d.get("action") == "rfid":
        handle_device({"type": "rfid", "uid": d.get("uid", "DEMO0001")})
    elif d.get("action") in ("ir1", "ir2"):
        s = int(d["action"][-1])
        handle_device({"type": "ir", "sensor": s, "state": True})
        handle_device({"type": "ir", "sensor": s, "state": False})
    else:
        return jsonify(error="unknown action"), 400
    return jsonify(ok=True)


@app.route("/api/analytics")
@login_required
def api_analytics():
    con = db()
    mv = [dict(r) for r in con.execute("SELECT * FROM movements ORDER BY id DESC LIMIT 500")]
    sched = con.execute("SELECT arr FROM schedules").fetchall()
    al = con.execute("SELECT status, COUNT(*) c FROM alerts GROUP BY status").fetchall()
    con.close()
    ts = list(sim["trains"].values())
    hourly = {f"{h:02d}:00": 0 for h in range(24)}
    for r in sched:
        hourly[r["arr"][:2] + ":00"] += 1
    cats = {}
    for t in ts:
        cats[t["category"]] = cats.get(t["category"], 0) + 1
    by_route = {}
    for m in mv:
        by_route[m["route"]] = by_route.get(m["route"], 0) + 1
    on_time = sum(1 for t in ts if t["delay"] <= 5)
    return jsonify(
        delay={f"#{t['number']}": t["delay"] for t in ts},
        hourly=hourly,
        punctuality={"On time": on_time, "Delayed": len(ts) - on_time},
        track_util={f"Track {k}": v for k, v in sim["util"].items()},
        categories=cats,
        resolution={r["status"]: r["c"] for r in al},
        rig={"total": len(mv), "by_route": by_route,
             "avg_transit": round(sum(m["transit_s"] for m in mv) / len(mv), 1) if mv else 0,
             "recent": mv[:10]})


# ------------------------------------------------- outbound link to the ESP32
# The ESP32 runs its own Wi-Fi access point + WebSocket server. This thread connects to it
# (default ws://192.168.4.1:81) and reconnects forever, so it "just works" once the laptop
# has joined the ESP32's Wi-Fi.  Set ESP_URL="" to disable (e.g. when deployed to the cloud).
ESP_URL = os.environ.get("ESP_URL", "ws://192.168.4.1:81")


def device_link():
    import websocket  # websocket-client
    while True:
        ws = None
        try:
            ws = websocket.create_connection(ESP_URL, timeout=4)
            ws.settimeout(20)
            with lock:
                devices.add(ws)
                state["device_online"] = True
                log("system", f"ESP32 connected at {ESP_URL}")
                _send(ws, {"type": "switch", "pos": state["switch"]})
                _send(ws, {"type": "lcd", "l1": state["lcd"][0], "l2": state["lcd"][1]})
                push_state()
            while True:
                try:
                    raw = ws.recv()
                except websocket.WebSocketTimeoutException:
                    ws.ping()
                    continue
                if not raw:
                    break
                try:
                    handle_device(json.loads(raw))
                except (ValueError, KeyError) as e:
                    log("error", f"Bad device message: {e}")
        except Exception:
            pass
        finally:
            with lock:
                if ws in devices:
                    devices.discard(ws)
                    state["device_online"] = bool(devices)
                    log("system", "ESP32 disconnected")
                    push_state()
            try:
                if ws:
                    ws.close()
            except Exception:
                pass
        time.sleep(2)


init_db()
seed_sim()
threading.Thread(target=sim_loop, daemon=True).start()
if ESP_URL:
    threading.Thread(target=device_link, daemon=True).start()

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", 5000)), threaded=True)
