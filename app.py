"""
app.py — Smart Seating Planner
Flask backend: session auth, SQLite, PBKDF2 password hashing,
               Venue Design Module, Seating Arrangement CSP (v0.3)
"""

import os
import json
import sqlite3
import hashlib
import secrets
from datetime import datetime
from functools import wraps
from flask import (
    Flask, render_template, request, redirect,
    url_for, session, flash, jsonify, g, Response
)

from seating_csp import (
    Participant, Constraint, ConstraintType, GridLayout, SeatingCSP
)

app = Flask(__name__)
app.secret_key = os.environ.get("SECRET_KEY", secrets.token_hex(32))

# Custom Jinja filter: parse a JSON string inside templates
app.jinja_env.filters["from_json"] = json.loads

DB_PATH = os.path.join(os.path.dirname(__file__), "seating.db")


# ── Database ─────────────────────────────────────────────────────────────────

def get_db():
    if "db" not in g:
        g.db = sqlite3.connect(DB_PATH, detect_types=sqlite3.PARSE_DECLTYPES)
        g.db.row_factory = sqlite3.Row
    return g.db


@app.teardown_appcontext
def close_db(exc=None):
    db = g.pop("db", None)
    if db:
        db.close()


def init_db():
    db = sqlite3.connect(DB_PATH)
    db.execute("""
        CREATE TABLE IF NOT EXISTS users (
            id         INTEGER PRIMARY KEY AUTOINCREMENT,
            username   TEXT    UNIQUE NOT NULL,
            email      TEXT    UNIQUE NOT NULL,
            password   TEXT    NOT NULL,
            role       TEXT    NOT NULL DEFAULT 'planner',
            created_at TEXT    NOT NULL
        )
    """)
    db.execute("""
        CREATE TABLE IF NOT EXISTS sessions (
            id         INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id    INTEGER NOT NULL,
            token      TEXT    NOT NULL,
            created_at TEXT    NOT NULL,
            FOREIGN KEY(user_id) REFERENCES users(id)
        )
    """)
    db.execute("""
        CREATE TABLE IF NOT EXISTS venues (
            id          INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id     INTEGER NOT NULL,
            name        TEXT    NOT NULL,
            description TEXT    NOT NULL DEFAULT '',
            venue_type  TEXT    NOT NULL DEFAULT 'classroom',
            rows        INTEGER NOT NULL,
            cols        INTEGER NOT NULL,
            layout_json TEXT    NOT NULL,
            created_at  TEXT    NOT NULL,
            updated_at  TEXT    NOT NULL,
            FOREIGN KEY(user_id) REFERENCES users(id)
        )
    """)
    db.execute("""
        CREATE TABLE IF NOT EXISTS participants (
            id              INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id         INTEGER NOT NULL,
            name            TEXT    NOT NULL,
            group_name      TEXT    NOT NULL DEFAULT '',
            needs_front_row INTEGER NOT NULL DEFAULT 0,
            needs_aisle     INTEGER NOT NULL DEFAULT 0,
            notes           TEXT    NOT NULL DEFAULT '',
            created_at      TEXT    NOT NULL,
            UNIQUE(user_id, name),
            FOREIGN KEY(user_id) REFERENCES users(id)
        )
    """)
    db.execute("""
        CREATE TABLE IF NOT EXISTS arrangements (
            id                INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id           INTEGER NOT NULL,
            venue_id          INTEGER,
            name              TEXT    NOT NULL,
            status            TEXT    NOT NULL DEFAULT 'unsolved',
            participants_json TEXT    NOT NULL DEFAULT '[]',
            constraints_json  TEXT    NOT NULL DEFAULT '[]',
            result_json       TEXT,
            created_at        TEXT    NOT NULL,
            updated_at        TEXT    NOT NULL,
            FOREIGN KEY(user_id)  REFERENCES users(id),
            FOREIGN KEY(venue_id) REFERENCES venues(id) ON DELETE SET NULL
        )
    """)
    db.commit()
    db.close()


# ── Password helpers ──────────────────────────────────────────────────────────

def hash_password(password: str) -> str:
    salt = secrets.token_hex(16)
    dk = hashlib.pbkdf2_hmac("sha256", password.encode(), salt.encode(), 260_000)
    return f"{salt}${dk.hex()}"


def verify_password(password: str, stored: str) -> bool:
    try:
        salt, dk_hex = stored.split("$", 1)
        dk = hashlib.pbkdf2_hmac("sha256", password.encode(), salt.encode(), 260_000)
        return secrets.compare_digest(dk.hex(), dk_hex)
    except Exception:
        return False


# ── Auth decorator ────────────────────────────────────────────────────────────

def login_required(f):
    @wraps(f)
    def decorated(*args, **kwargs):
        if "user_id" not in session:
            flash("Please log in to continue.", "info")
            return redirect(url_for("auth"))
        return f(*args, **kwargs)
    return decorated


# ── Venue helpers ─────────────────────────────────────────────────────────────

def build_layout_json(rows: int, cols: int, seats_override: dict = None) -> dict:
    """
    Build the canonical venue JSON layout.

    JSON schema
    -----------
    {
      "schema_version": "1.0",
      "rows": int,
      "cols": int,
      "seats": {
        "R1C1": {
          "id":         "R1C1",
          "row":        0,          // 0-based
          "col":        0,          // 0-based
          "type":       "normal",   // normal | blocked | aisle | front | exit
          "label":      "",         // custom label / name
          "is_blocked": false,
          "is_aisle":   false,
          "is_front":   false
        }, ...
      },
      "stats": {
        "total":     int,
        "available": int,
        "blocked":   int,
        "aisle":     int,
        "front":     int
      }
    }
    """
    seats = {}
    for r in range(rows):
        for c in range(cols):
            sid = f"R{r+1}C{c+1}"
            is_aisle = (c == 0 or c == cols - 1)
            is_front = (r == 0)
            seat_type = "front" if is_front else ("aisle" if is_aisle else "normal")

            if seats_override and sid in seats_override:
                seat = dict(seats_override[sid])
                seat["id"]       = sid
                seat["row"]      = r
                seat["col"]      = c
                seat["is_front"] = is_front
                seats[sid] = seat
            else:
                seats[sid] = {
                    "id":         sid,
                    "row":        r,
                    "col":        c,
                    "type":       seat_type,
                    "label":      "",
                    "is_blocked": False,
                    "is_aisle":   is_aisle,
                    "is_front":   is_front,
                }

    stats = compute_stats(seats)
    return {
        "schema_version": "1.0",
        "rows":  rows,
        "cols":  cols,
        "seats": seats,
        "stats": stats,
    }


def compute_stats(seats: dict) -> dict:
    total     = len(seats)
    blocked   = sum(1 for s in seats.values() if s.get("is_blocked"))
    aisle     = sum(1 for s in seats.values() if s.get("is_aisle") and not s.get("is_blocked"))
    front     = sum(1 for s in seats.values() if s.get("is_front") and not s.get("is_blocked"))
    available = total - blocked
    return {
        "total":     total,
        "available": available,
        "blocked":   blocked,
        "aisle":     aisle,
        "front":     front,
    }


def venue_to_api(row) -> dict:
    """Convert a sqlite Row to a JSON-serialisable dict."""
    layout = json.loads(row["layout_json"])
    return {
        "id":          row["id"],
        "name":        row["name"],
        "description": row["description"],
        "venue_type":  row["venue_type"],
        "rows":        row["rows"],
        "cols":        row["cols"],
        "layout":      layout,
        "created_at":  row["created_at"],
        "updated_at":  row["updated_at"],
    }


# ── Routes: pages ─────────────────────────────────────────────────────────────

@app.route("/")
def index():
    if "user_id" in session:
        return redirect(url_for("dashboard"))
    return redirect(url_for("auth"))


@app.route("/auth", methods=["GET", "POST"])
def auth():
    if "user_id" in session:
        return redirect(url_for("dashboard"))

    if request.method == "POST":
        action = request.form.get("action")

        if action == "login":
            identifier = request.form.get("identifier", "").strip()
            password   = request.form.get("password", "")
            db   = get_db()
            user = db.execute(
                "SELECT * FROM users WHERE username = ? OR email = ?",
                (identifier, identifier)
            ).fetchone()
            if user and verify_password(password, user["password"]):
                session.permanent = True
                session["user_id"]  = user["id"]
                session["username"] = user["username"]
                session["role"]     = user["role"]
                return redirect(url_for("dashboard"))
            flash("Invalid credentials. Please try again.", "error")
            return redirect(url_for("auth") + "?tab=login")

        elif action == "register":
            username = request.form.get("username", "").strip()
            email    = request.form.get("email", "").strip().lower()
            password = request.form.get("password", "")
            confirm  = request.form.get("confirm", "")
            if len(username) < 3:
                flash("Username must be at least 3 characters.", "error")
                return redirect(url_for("auth") + "?tab=register")
            if len(password) < 8:
                flash("Password must be at least 8 characters.", "error")
                return redirect(url_for("auth") + "?tab=register")
            if password != confirm:
                flash("Passwords do not match.", "error")
                return redirect(url_for("auth") + "?tab=register")
            db = get_db()
            try:
                db.execute(
                    "INSERT INTO users (username, email, password, role, created_at) VALUES (?,?,?,?,?)",
                    (username, email, hash_password(password), "planner",
                     datetime.utcnow().isoformat())
                )
                db.commit()
                flash("Account created! You can now log in.", "success")
                return redirect(url_for("auth") + "?tab=login")
            except sqlite3.IntegrityError:
                flash("Username or email already taken.", "error")
                return redirect(url_for("auth") + "?tab=register")

    active_tab = request.args.get("tab", "login")
    return render_template("auth.html", active_tab=active_tab)


@app.route("/dashboard")
@login_required
def dashboard():
    db  = get_db()
    uid = session["user_id"]
    user = db.execute("SELECT * FROM users WHERE id = ?", (uid,)).fetchone()

    venue_count = db.execute(
        "SELECT COUNT(*) as cnt FROM venues WHERE user_id = ?", (uid,)
    ).fetchone()["cnt"]

    arrangement_count = db.execute(
        "SELECT COUNT(*) as cnt FROM arrangements WHERE user_id = ?", (uid,)
    ).fetchone()["cnt"]

    solved_count = db.execute(
        "SELECT COUNT(*) as cnt FROM arrangements WHERE user_id = ? AND status = 'solved'", (uid,)
    ).fetchone()["cnt"]

    # Total participants across all arrangements
    all_parts = db.execute(
        "SELECT participants_json FROM arrangements WHERE user_id = ?", (uid,)
    ).fetchall()
    participant_total = sum(
        len(json.loads(r["participants_json"])) for r in all_parts
    )

    # Recent arrangements (last 5)
    recent = db.execute(
        """SELECT a.*, v.name as venue_name
           FROM arrangements a
           LEFT JOIN venues v ON a.venue_id = v.id
           WHERE a.user_id = ?
           ORDER BY a.updated_at DESC LIMIT 5""",
        (uid,)
    ).fetchall()

    return render_template(
        "dashboard.html",
        user=user,
        venue_count=venue_count,
        arrangement_count=arrangement_count,
        solved_count=solved_count,
        participant_total=participant_total,
        recent=recent,
    )


@app.route("/venues")
@login_required
def venues_list():
    db     = get_db()
    user   = db.execute("SELECT * FROM users WHERE id = ?", (session["user_id"],)).fetchone()
    venues = db.execute(
        "SELECT * FROM venues WHERE user_id = ? ORDER BY updated_at DESC",
        (session["user_id"],)
    ).fetchall()
    return render_template("venues.html", user=user, venues=venues)


@app.route("/venues/new")
@login_required
def venue_new():
    db   = get_db()
    user = db.execute("SELECT * FROM users WHERE id = ?", (session["user_id"],)).fetchone()
    return render_template("venue_editor.html", user=user, venue=None)


@app.route("/venues/<int:venue_id>/edit")
@login_required
def venue_edit(venue_id):
    db    = get_db()
    user  = db.execute("SELECT * FROM users WHERE id = ?", (session["user_id"],)).fetchone()
    venue = db.execute(
        "SELECT * FROM venues WHERE id = ? AND user_id = ?",
        (venue_id, session["user_id"])
    ).fetchone()
    if not venue:
        flash("Venue not found.", "error")
        return redirect(url_for("venues_list"))
    return render_template("venue_editor.html", user=user, venue=venue)


@app.route("/logout", methods=["POST"])
def logout():
    session.clear()
    flash("You've been logged out.", "info")
    return redirect(url_for("auth"))


# ── Routes: Venue JSON API ────────────────────────────────────────────────────

@app.route("/api/venues", methods=["GET"])
@login_required
def api_venues_list():
    db     = get_db()
    venues = db.execute(
        "SELECT * FROM venues WHERE user_id = ? ORDER BY updated_at DESC",
        (session["user_id"],)
    ).fetchall()
    return jsonify([venue_to_api(v) for v in venues])


@app.route("/api/venues", methods=["POST"])
@login_required
def api_venue_create():
    data = request.get_json(silent=True) or {}
    name        = (data.get("name") or "").strip()
    description = (data.get("description") or "").strip()
    venue_type  = data.get("venue_type", "classroom")
    rows        = int(data.get("rows", 5))
    cols        = int(data.get("cols", 6))
    seats_data  = data.get("seats")          # optional: pre-filled seat states

    if not name:
        return jsonify({"error": "name is required"}), 400
    if not (1 <= rows <= 30 and 1 <= cols <= 30):
        return jsonify({"error": "rows and cols must be between 1 and 30"}), 400

    now    = datetime.utcnow().isoformat()
    layout = build_layout_json(rows, cols, seats_override=seats_data)
    layout["metadata"] = {"created_at": now, "updated_at": now,
                           "venue_type": venue_type, "name": name,
                           "description": description}

    db = get_db()
    cur = db.execute(
        """INSERT INTO venues (user_id, name, description, venue_type,
                               rows, cols, layout_json, created_at, updated_at)
           VALUES (?,?,?,?,?,?,?,?,?)""",
        (session["user_id"], name, description, venue_type,
         rows, cols, json.dumps(layout), now, now)
    )
    db.commit()
    venue = db.execute("SELECT * FROM venues WHERE id = ?", (cur.lastrowid,)).fetchone()
    return jsonify(venue_to_api(venue)), 201


@app.route("/api/venues/<int:venue_id>", methods=["GET"])
@login_required
def api_venue_get(venue_id):
    db    = get_db()
    venue = db.execute(
        "SELECT * FROM venues WHERE id = ? AND user_id = ?",
        (venue_id, session["user_id"])
    ).fetchone()
    if not venue:
        return jsonify({"error": "not found"}), 404
    return jsonify(venue_to_api(venue))


@app.route("/api/venues/<int:venue_id>", methods=["PUT"])
@login_required
def api_venue_update(venue_id):
    db    = get_db()
    venue = db.execute(
        "SELECT * FROM venues WHERE id = ? AND user_id = ?",
        (venue_id, session["user_id"])
    ).fetchone()
    if not venue:
        return jsonify({"error": "not found"}), 404

    data        = request.get_json(silent=True) or {}
    name        = (data.get("name") or venue["name"]).strip()
    description = (data.get("description", venue["description"]) or "").strip()
    venue_type  = data.get("venue_type", venue["venue_type"])
    rows        = int(data.get("rows", venue["rows"]))
    cols        = int(data.get("cols", venue["cols"]))
    seats_data  = data.get("seats")

    if not name:
        return jsonify({"error": "name is required"}), 400
    if not (1 <= rows <= 30 and 1 <= cols <= 30):
        return jsonify({"error": "rows and cols must be between 1 and 30"}), 400

    now    = datetime.utcnow().isoformat()
    old_layout = json.loads(venue["layout_json"])
    layout = build_layout_json(rows, cols, seats_override=seats_data)
    layout["metadata"] = {
        **(old_layout.get("metadata") or {}),
        "updated_at":  now,
        "venue_type":  venue_type,
        "name":        name,
        "description": description,
    }

    db.execute(
        """UPDATE venues SET name=?, description=?, venue_type=?,
                             rows=?, cols=?, layout_json=?, updated_at=?
           WHERE id=?""",
        (name, description, venue_type, rows, cols,
         json.dumps(layout), now, venue_id)
    )
    db.commit()
    updated = db.execute("SELECT * FROM venues WHERE id = ?", (venue_id,)).fetchone()
    return jsonify(venue_to_api(updated))


@app.route("/api/venues/<int:venue_id>", methods=["DELETE"])
@login_required
def api_venue_delete(venue_id):
    db = get_db()
    existing = db.execute(
        "SELECT id FROM venues WHERE id = ? AND user_id = ?",
        (venue_id, session["user_id"])
    ).fetchone()
    if not existing:
        return jsonify({"error": "not found"}), 404
    db.execute("DELETE FROM venues WHERE id = ?", (venue_id,))
    db.commit()
    return jsonify({"deleted": venue_id})


@app.route("/api/venues/<int:venue_id>/export")
@login_required
def api_venue_export(venue_id):
    """Download the venue layout as a pretty-printed JSON file."""
    db    = get_db()
    venue = db.execute(
        "SELECT * FROM venues WHERE id = ? AND user_id = ?",
        (venue_id, session["user_id"])
    ).fetchone()
    if not venue:
        return jsonify({"error": "not found"}), 404

    payload = venue_to_api(venue)
    pretty  = json.dumps(payload, indent=2, ensure_ascii=False)
    safe_name = "".join(c if c.isalnum() or c in "-_ " else "_" for c in venue["name"])
    filename  = f"venue_{safe_name.replace(' ', '_')}.json"
    return Response(
        pretty,
        mimetype="application/json",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'}
    )


# ── General API ───────────────────────────────────────────────────────────────

@app.route("/api/health")
def health():
    return jsonify({"status": "ok", "version": "0.5.0"})


# ── Export module ─────────────────────────────────────────────────────────────

import csv, io

@app.route("/export")
@login_required
def export_hub():
    db  = get_db()
    uid = session["user_id"]
    user = db.execute("SELECT * FROM users WHERE id = ?", (uid,)).fetchone()

    venues = db.execute(
        "SELECT id, name, rows, cols, venue_type, updated_at FROM venues WHERE user_id = ? ORDER BY name",
        (uid,)
    ).fetchall()

    arrangements = db.execute(
        """SELECT a.id, a.name, a.status, a.updated_at, a.participants_json,
                  a.constraints_json, a.result_json, v.name as venue_name
           FROM arrangements a
           LEFT JOIN venues v ON a.venue_id = v.id
           WHERE a.user_id = ? ORDER BY a.name""",
        (uid,)
    ).fetchall()

    participant_count = db.execute(
        "SELECT COUNT(*) as cnt FROM participants WHERE user_id = ?", (uid,)
    ).fetchone()["cnt"]

    return render_template(
        "export.html",
        user=user,
        venues=venues,
        arrangements=arrangements,
        participant_count=participant_count,
    )


# ── Export: Participants ──────────────────────────────────────────────────────

@app.route("/api/export/participants.json")
@login_required
def export_participants_json():
    db   = get_db()
    rows = db.execute(
        "SELECT * FROM participants WHERE user_id = ? ORDER BY name",
        (session["user_id"],)
    ).fetchall()
    payload = {
        "exported_at": datetime.utcnow().isoformat(),
        "count": len(rows),
        "participants": [dict(r) for r in rows],
    }
    return Response(
        json.dumps(payload, indent=2),
        mimetype="application/json",
        headers={"Content-Disposition": 'attachment; filename="participants.json"'}
    )


@app.route("/api/export/participants.csv")
@login_required
def export_participants_csv():
    db   = get_db()
    rows = db.execute(
        "SELECT name, group_name, needs_front_row, needs_aisle, notes, created_at"
        " FROM participants WHERE user_id = ? ORDER BY name",
        (session["user_id"],)
    ).fetchall()
    buf = io.StringIO()
    w   = csv.writer(buf)
    w.writerow(["name", "group", "needs_front_row", "needs_aisle", "notes", "created_at"])
    for r in rows:
        w.writerow([r["name"], r["group_name"],
                    "yes" if r["needs_front_row"] else "no",
                    "yes" if r["needs_aisle"]     else "no",
                    r["notes"], r["created_at"]])
    return Response(
        buf.getvalue(),
        mimetype="text/csv",
        headers={"Content-Disposition": 'attachment; filename="participants.csv"'}
    )


# ── Export: Arrangements ──────────────────────────────────────────────────────

@app.route("/api/export/arrangements/<int:arr_id>/assignment.csv")
@login_required
def export_arrangement_csv(arr_id):
    db  = get_db()
    row = db.execute(
        "SELECT * FROM arrangements WHERE id = ? AND user_id = ?",
        (arr_id, session["user_id"])
    ).fetchone()
    if not row:
        return jsonify({"error": "not found"}), 404

    parts   = json.loads(row["participants_json"])
    result  = json.loads(row["result_json"]) if row["result_json"] else {}
    assign  = result.get("assignment", {})   # { name: seat_id }

    # Build a name → participant-details map
    p_map = {p["name"]: p for p in parts}

    buf = io.StringIO()
    w   = csv.writer(buf)
    w.writerow(["participant", "group", "seat", "row", "col",
                "needs_front_row", "needs_aisle", "status"])

    if assign:
        for name, seat_id in sorted(assign.items()):
            p = p_map.get(name, {})
            # parse seat_id: R2C3 → row=2, col=3
            try:
                parts_seat = seat_id.replace("R","").split("C")
                row_n, col_n = parts_seat[0], parts_seat[1]
            except Exception:
                row_n = col_n = ""
            w.writerow([
                name,
                p.get("group") or p.get("group_name") or "",
                seat_id,
                row_n, col_n,
                "yes" if p.get("needs_front_row") else "no",
                "yes" if p.get("needs_aisle")     else "no",
                row["status"],
            ])
    else:
        # Unsolved — just list participants
        for p in parts:
            w.writerow([p["name"],
                        p.get("group") or p.get("group_name") or "",
                        "", "", "",
                        "yes" if p.get("needs_front_row") else "no",
                        "yes" if p.get("needs_aisle")     else "no",
                        row["status"]])

    safe = "".join(c if c.isalnum() or c in "-_ " else "_" for c in row["name"])
    fname = f"arrangement_{safe.replace(' ','_')}_assignment.csv"
    return Response(
        buf.getvalue(),
        mimetype="text/csv",
        headers={"Content-Disposition": f'attachment; filename="{fname}"'}
    )


# ── Export: Image (PNG / JPEG) ────────────────────────────────────────────────

def _build_seating_image(row, fmt: str):
    """
    Draw a seating chart image with Pillow.
    Returns (bytes, mimetype, filename).
    fmt: 'png' or 'jpeg'
    """
    from PIL import Image, ImageDraw, ImageFont
    import io as _io

    parts   = json.loads(row["participants_json"])
    result  = json.loads(row["result_json"]) if row["result_json"] else {}
    assign  = result.get("assignment", {})      # { name: seat_id }
    p_map   = {p["name"]: p for p in parts}

    # Fetch venue layout for dimensions & blocked seats
    db        = get_db()
    venue_row = db.execute("SELECT * FROM venues WHERE id = ?", (row["venue_id"],)).fetchone() if row["venue_id"] else None
    if venue_row:
        layout    = json.loads(venue_row["layout_json"])
        grid_rows = venue_row["rows"]
        grid_cols = venue_row["cols"]
        seats_meta = layout.get("seats", {})
    else:
        # Derive grid from assignment seat ids
        if assign:
            ids = list(assign.values())
            grid_rows = max(int(s.split("C")[0][1:]) for s in ids)
            grid_cols = max(int(s.split("C")[1])     for s in ids)
        else:
            grid_rows, grid_cols = 1, 1
        seats_meta = {}

    # ── Colour palette (group → RGB) ────────────────────────────────────────
    GROUP_PALETTE = [
        (240, 165,   0),   # amber
        ( 59, 130, 246),   # blue
        ( 34, 197,  94),   # green
        (168,  85, 247),   # purple
        (236,  72, 153),   # pink
        (249, 115,  22),   # orange
        ( 20, 184, 166),   # teal
        (239,  68,  68),   # red
    ]
    groups = list({p.get("group") or p.get("group_name") or "" for p in parts if p.get("group") or p.get("group_name")})
    group_color = {}
    for i, g in enumerate(sorted(groups)):
        group_color[g] = GROUP_PALETTE[i % len(GROUP_PALETTE)]

    # ── Layout constants ─────────────────────────────────────────────────────
    CELL      = 80          # seat cell px
    GAP       = 6           # gap between cells
    MARGIN    = 48          # outer margin
    HDR       = 56          # top header area (title + row labels)
    LABEL_W   = 34          # row-label column width
    FONT_SIZE = 11

    W = MARGIN + LABEL_W + grid_cols * (CELL + GAP) - GAP + MARGIN
    H = HDR + MARGIN + grid_rows * (CELL + GAP) - GAP + MARGIN

    BG    = (11,  14,  20)
    PANEL = (22,  28,  44)
    BORDER= (31,  43,  69)
    TEXT  = (232, 236, 244)
    MUTED = (107, 122, 155)

    img  = Image.new("RGB", (W, H), BG)
    draw = ImageDraw.Draw(img)

    # Try loading a font, fall back to default
    try:
        font_sm   = ImageFont.truetype("/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",      FONT_SIZE)
        font_bold = ImageFont.truetype("/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf", FONT_SIZE)
        font_name = ImageFont.truetype("/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf", 10)
    except Exception:
        font_sm = font_bold = font_name = ImageFont.load_default()

    # Title
    title = row["name"]
    draw.text((MARGIN, 14), title, font=font_bold, fill=TEXT)
    status_color = (34, 197, 94) if row["status"] == "solved" else (239, 68, 68) if row["status"] == "infeasible" else (240, 165, 0)
    draw.text((MARGIN, 34), f"Status: {row['status'].upper()}  ·  {len(assign)}/{len(parts)} seated", font=font_sm, fill=status_color)

    # Column headers
    for c in range(grid_cols):
        cx = MARGIN + LABEL_W + c * (CELL + GAP) + CELL // 2
        draw.text((cx, HDR - 14), f"C{c+1}", font=font_sm, fill=MUTED, anchor="mm")

    # Reverse map: seat_id → participant name
    seat_to_name = {v: k for k, v in assign.items()}

    for r in range(grid_rows):
        # Row label
        ry = HDR + MARGIN // 2 + r * (CELL + GAP)
        draw.text((MARGIN + LABEL_W - 6, ry + CELL // 2), f"R{r+1}", font=font_sm, fill=MUTED, anchor="rm")

        for c in range(grid_cols):
            sid  = f"R{r+1}C{c+1}"
            smeta = seats_meta.get(sid, {})
            is_blocked = smeta.get("is_blocked") or smeta.get("type") == "blocked"
            is_front   = smeta.get("is_front")   or smeta.get("type") == "front"
            is_aisle   = smeta.get("is_aisle")   or smeta.get("type") == "aisle"

            x0 = MARGIN + LABEL_W + c * (CELL + GAP)
            y0 = ry
            x1, y1 = x0 + CELL, y0 + CELL
            radius = 6

            if is_blocked:
                # Dark blocked seat
                draw.rounded_rectangle([x0, y0, x1, y1], radius=radius, fill=(13, 16, 23), outline=BORDER)
                # X mark
                draw.line([x0+12, y0+12, x1-12, y1-12], fill=MUTED, width=2)
                draw.line([x1-12, y0+12, x0+12, y1-12], fill=MUTED, width=2)
            elif sid in seat_to_name:
                pname = seat_to_name[sid]
                p     = p_map.get(pname, {})
                grp   = p.get("group") or p.get("group_name") or ""
                color = group_color.get(grp, (59, 130, 246))
                bg    = tuple(max(0, v - 180) for v in color)   # very dark tint
                # Filled seat
                draw.rounded_rectangle([x0, y0, x1, y1], radius=radius,
                                        fill=bg, outline=color, width=2)
                # Colored top bar
                draw.rounded_rectangle([x0, y0, x1, y0 + 4], radius=2, fill=color)
                # Name text (wrap at 9 chars)
                short = pname if len(pname) <= 10 else pname[:9] + "…"
                draw.text((x0 + CELL//2, y0 + CELL//2), short,
                          font=font_name, fill=TEXT, anchor="mm")
            else:
                # Empty seat
                fill_color = PANEL
                outline_color = BORDER
                if is_front:
                    outline_color = (59, 80, 150)
                if is_aisle:
                    outline_color = (30, 90, 60)
                draw.rounded_rectangle([x0, y0, x1, y1], radius=radius,
                                        fill=fill_color, outline=outline_color)

    # Legend at bottom
    leg_x = MARGIN
    leg_y = HDR + MARGIN // 2 + grid_rows * (CELL + GAP) + 8
    if leg_y + 20 < H:
        if groups:
            draw.text((leg_x, leg_y), "Groups: ", font=font_sm, fill=MUTED)
            leg_x += 55
            for g in sorted(groups)[:6]:
                c = group_color.get(g, (100, 100, 100))
                draw.rectangle([leg_x, leg_y + 2, leg_x + 10, leg_y + 12], fill=c)
                draw.text((leg_x + 14, leg_y), g, font=font_sm, fill=MUTED)
                leg_x += 14 + len(g) * 7 + 10

    # Render to bytes
    buf = _io.BytesIO()
    if fmt == "jpeg":
        img.save(buf, format="JPEG", quality=92, optimize=True)
        mime  = "image/jpeg"
    else:
        img.save(buf, format="PNG", optimize=True)
        mime  = "image/png"
    buf.seek(0)

    safe  = "".join(ch if ch.isalnum() or ch in "-_ " else "_" for ch in row["name"])
    fname = f"arrangement_{safe.replace(' ','_')}.{fmt}"
    return buf.getvalue(), mime, fname


@app.route("/api/export/arrangements/<int:arr_id>/image.<fmt>")
@login_required
def export_arrangement_image(arr_id, fmt):
    if fmt not in ("png", "jpeg", "jpg"):
        return jsonify({"error": "unsupported format — use png or jpeg"}), 400
    if fmt == "jpg":
        fmt = "jpeg"

    db  = get_db()
    row = db.execute(
        "SELECT * FROM arrangements WHERE id = ? AND user_id = ?",
        (arr_id, session["user_id"])
    ).fetchone()
    if not row:
        return jsonify({"error": "not found"}), 404
    if not row["result_json"]:
        return jsonify({"error": "arrangement has not been solved yet"}), 400

    data, mime, fname = _build_seating_image(row, fmt)
    return Response(
        data,
        mimetype=mime,
        headers={"Content-Disposition": f'attachment; filename="{fname}"'}
    )


# ── Arrangement helpers ───────────────────────────────────────────────────────

def arrangement_to_api(row) -> dict:
    return {
        "id":           row["id"],
        "venue_id":     row["venue_id"],
        "name":         row["name"],
        "status":       row["status"],
        "participants": json.loads(row["participants_json"]),
        "constraints":  json.loads(row["constraints_json"]),
        "result":       json.loads(row["result_json"]) if row["result_json"] else None,
        "created_at":   row["created_at"],
        "updated_at":   row["updated_at"],
    }


def build_csp_layout(venue_row) -> GridLayout:
    """Convert a saved venue DB row into a SeatingCSP GridLayout."""
    layout   = json.loads(venue_row["layout_json"])
    seats    = layout.get("seats", {})
    rows     = venue_row["rows"]
    cols     = venue_row["cols"]

    blocked  = [sid for sid, s in seats.items() if s.get("is_blocked") or s.get("type") == "blocked"]
    aisle_cols_set = set()
    for s in seats.values():
        if s.get("is_aisle") or s.get("type") == "aisle":
            aisle_cols_set.add(s["col"])   # 0-based

    return GridLayout(
        rows=rows,
        cols=cols,
        blocked_seats=blocked,
        aisle_cols=list(aisle_cols_set) if aisle_cols_set else None,
    )


def build_csp_participants(participants_data: list) -> list[Participant]:
    out = []
    for p in participants_data:
        out.append(Participant(
            name=p["name"],
            group=p.get("group") or None,
            needs_front_row=bool(p.get("needs_front_row")),
            needs_aisle=bool(p.get("needs_aisle")),
            reserved_seat=p.get("reserved_seat") or None,
        ))
    return out


_CTYPE_MAP = {
    "MUST_SIT_TOGETHER":     ConstraintType.MUST_SIT_TOGETHER,
    "MUST_NOT_SIT_TOGETHER": ConstraintType.MUST_NOT_SIT_TOGETHER,
    "SAME_GROUP_TOGETHER":   ConstraintType.SAME_GROUP_TOGETHER,
    "SAME_GROUP_APART":      ConstraintType.SAME_GROUP_APART,
    "FRONT_ROW":             ConstraintType.FRONT_ROW,
    "NEAR_AISLE":            ConstraintType.NEAR_AISLE,
    "SPECIFIC_SEAT":         ConstraintType.SPECIFIC_SEAT,
    "RESERVED_SEAT":         ConstraintType.RESERVED_SEAT,
}

def build_csp_constraints(constraints_data: list) -> list[Constraint]:
    out = []
    for c in constraints_data:
        ctype = _CTYPE_MAP.get(c.get("type", ""))
        if not ctype:
            continue
        out.append(Constraint(
            constraint_type=ctype,
            participants=c.get("participants", []),
            group=c.get("group") or None,
            seat_id=c.get("seat_id") or None,
        ))
    return out


# ── Routes: Participant pages & API ──────────────────────────────────────────

@app.route("/participants")
@login_required
def participants_list():
    db   = get_db()
    user = db.execute("SELECT * FROM users WHERE id = ?", (session["user_id"],)).fetchone()
    rows = db.execute(
        "SELECT * FROM participants WHERE user_id = ? ORDER BY name ASC",
        (session["user_id"],)
    ).fetchall()
    return render_template("participants.html", user=user, participants=[dict(r) for r in rows])


@app.route("/api/participants", methods=["GET"])
@login_required
def api_participants_list():
    db   = get_db()
    rows = db.execute(
        "SELECT * FROM participants WHERE user_id = ? ORDER BY name ASC",
        (session["user_id"],)
    ).fetchall()
    return jsonify([dict(r) for r in rows])


@app.route("/api/participants", methods=["POST"])
@login_required
def api_participant_create():
    data = request.get_json(silent=True) or {}
    name  = (data.get("name") or "").strip()
    if not name:
        return jsonify({"error": "name is required"}), 400
    now = datetime.utcnow().isoformat()
    db  = get_db()
    try:
        cur = db.execute(
            """INSERT INTO participants
               (user_id, name, group_name, needs_front_row, needs_aisle, notes, created_at)
               VALUES (?,?,?,?,?,?,?)""",
            (session["user_id"], name,
             (data.get("group_name") or "").strip(),
             1 if data.get("needs_front_row") else 0,
             1 if data.get("needs_aisle")     else 0,
             (data.get("notes") or "").strip(),
             now)
        )
        db.commit()
        row = db.execute("SELECT * FROM participants WHERE id = ?", (cur.lastrowid,)).fetchone()
        return jsonify(dict(row)), 201
    except sqlite3.IntegrityError:
        return jsonify({"error": f"A participant named '{name}' already exists."}), 409


@app.route("/api/participants/<int:pid>", methods=["PUT"])
@login_required
def api_participant_update(pid):
    db  = get_db()
    row = db.execute(
        "SELECT * FROM participants WHERE id = ? AND user_id = ?",
        (pid, session["user_id"])
    ).fetchone()
    if not row:
        return jsonify({"error": "not found"}), 404
    data = request.get_json(silent=True) or {}
    name = (data.get("name") or row["name"]).strip()
    if not name:
        return jsonify({"error": "name is required"}), 400
    try:
        db.execute(
            """UPDATE participants SET name=?, group_name=?, needs_front_row=?,
               needs_aisle=?, notes=? WHERE id=?""",
            (name,
             (data.get("group_name", row["group_name"]) or "").strip(),
             1 if data.get("needs_front_row") else 0,
             1 if data.get("needs_aisle")     else 0,
             (data.get("notes", row["notes"]) or "").strip(),
             pid)
        )
        db.commit()
        updated = db.execute("SELECT * FROM participants WHERE id = ?", (pid,)).fetchone()
        return jsonify(dict(updated))
    except sqlite3.IntegrityError:
        return jsonify({"error": f"A participant named '{name}' already exists."}), 409


@app.route("/api/participants/<int:pid>", methods=["DELETE"])
@login_required
def api_participant_delete(pid):
    db = get_db()
    row = db.execute(
        "SELECT id FROM participants WHERE id = ? AND user_id = ?",
        (pid, session["user_id"])
    ).fetchone()
    if not row:
        return jsonify({"error": "not found"}), 404
    db.execute("DELETE FROM participants WHERE id = ?", (pid,))
    db.commit()
    return jsonify({"deleted": pid})


# ── Routes: Arrangement pages ─────────────────────────────────────────────────

@app.route("/arrangements")
@login_required
def arrangements_list():
    db   = get_db()
    user = db.execute("SELECT * FROM users WHERE id = ?", (session["user_id"],)).fetchone()
    rows = db.execute(
        """SELECT a.*, v.name as venue_name
           FROM arrangements a
           LEFT JOIN venues v ON a.venue_id = v.id
           WHERE a.user_id = ?
           ORDER BY a.updated_at DESC""",
        (session["user_id"],)
    ).fetchall()
    return render_template("arrangements.html", user=user, arrangements=rows)


@app.route("/arrangements/new")
@login_required
def arrangement_new():
    db     = get_db()
    user   = db.execute("SELECT * FROM users WHERE id = ?", (session["user_id"],)).fetchone()
    venues = db.execute(
        "SELECT id, name, rows, cols FROM venues WHERE user_id = ? ORDER BY name",
        (session["user_id"],)
    ).fetchall()
    return render_template("arrangement_editor.html", user=user,
                           arrangement=None, venues=venues)


@app.route("/arrangements/<int:arr_id>")
@login_required
def arrangement_view(arr_id):
    db  = get_db()
    user = db.execute("SELECT * FROM users WHERE id = ?", (session["user_id"],)).fetchone()
    row  = db.execute(
        "SELECT * FROM arrangements WHERE id = ? AND user_id = ?",
        (arr_id, session["user_id"])
    ).fetchone()
    if not row:
        flash("Arrangement not found.", "error")
        return redirect(url_for("arrangements_list"))
    venues = db.execute(
        "SELECT id, name, rows, cols FROM venues WHERE user_id = ? ORDER BY name",
        (session["user_id"],)
    ).fetchall()
    venue = None
    if row["venue_id"]:
        venue = db.execute("SELECT * FROM venues WHERE id = ?", (row["venue_id"],)).fetchone()
    return render_template("arrangement_editor.html", user=user,
                           arrangement=row, venues=venues, venue=venue)


# ── Routes: Arrangement API ───────────────────────────────────────────────────

@app.route("/api/arrangements", methods=["GET"])
@login_required
def api_arrangements_list():
    db   = get_db()
    rows = db.execute(
        "SELECT * FROM arrangements WHERE user_id = ? ORDER BY updated_at DESC",
        (session["user_id"],)
    ).fetchall()
    return jsonify([arrangement_to_api(r) for r in rows])


@app.route("/api/arrangements", methods=["POST"])
@login_required
def api_arrangement_create():
    """Create (and optionally immediately solve) an arrangement."""
    data     = request.get_json(silent=True) or {}
    name     = (data.get("name") or "").strip()
    venue_id = data.get("venue_id")
    parts    = data.get("participants", [])
    constrs  = data.get("constraints", [])

    if not name:
        return jsonify({"error": "name is required"}), 400

    now = datetime.utcnow().isoformat()
    db  = get_db()

    # Verify venue belongs to user
    venue_row = None
    if venue_id:
        venue_row = db.execute(
            "SELECT * FROM venues WHERE id = ? AND user_id = ?",
            (venue_id, session["user_id"])
        ).fetchone()
        if not venue_row:
            return jsonify({"error": "venue not found"}), 404

    cur = db.execute(
        """INSERT INTO arrangements
           (user_id, venue_id, name, status, participants_json, constraints_json,
            result_json, created_at, updated_at)
           VALUES (?,?,?,?,?,?,NULL,?,?)""",
        (session["user_id"], venue_id, name, "unsolved",
         json.dumps(parts), json.dumps(constrs), now, now)
    )
    db.commit()
    arr_id = cur.lastrowid

    # If solve=true in payload, run the CSP immediately
    if data.get("solve") and venue_row and parts:
        result, error = _run_csp(venue_row, parts, constrs)
        status = "solved" if result else "infeasible"
        result_json = json.dumps(result) if result else json.dumps({"error": error})
        db.execute(
            "UPDATE arrangements SET status=?, result_json=?, updated_at=? WHERE id=?",
            (status, result_json, datetime.utcnow().isoformat(), arr_id)
        )
        db.commit()

    row = db.execute("SELECT * FROM arrangements WHERE id = ?", (arr_id,)).fetchone()
    return jsonify(arrangement_to_api(row)), 201


@app.route("/api/arrangements/<int:arr_id>", methods=["PUT"])
@login_required
def api_arrangement_update(arr_id):
    db  = get_db()
    row = db.execute(
        "SELECT * FROM arrangements WHERE id = ? AND user_id = ?",
        (arr_id, session["user_id"])
    ).fetchone()
    if not row:
        return jsonify({"error": "not found"}), 404

    data     = request.get_json(silent=True) or {}
    name     = (data.get("name") or row["name"]).strip()
    venue_id = data.get("venue_id", row["venue_id"])
    parts    = data.get("participants", json.loads(row["participants_json"]))
    constrs  = data.get("constraints",  json.loads(row["constraints_json"]))
    now      = datetime.utcnow().isoformat()

    db.execute(
        """UPDATE arrangements SET name=?, venue_id=?, participants_json=?,
           constraints_json=?, updated_at=? WHERE id=?""",
        (name, venue_id, json.dumps(parts), json.dumps(constrs), now, arr_id)
    )
    db.commit()
    updated = db.execute("SELECT * FROM arrangements WHERE id = ?", (arr_id,)).fetchone()
    return jsonify(arrangement_to_api(updated))


@app.route("/api/arrangements/<int:arr_id>/solve", methods=["POST"])
@login_required
def api_arrangement_solve(arr_id):
    """(Re-)run the CSP solver on the saved arrangement."""
    db  = get_db()
    row = db.execute(
        "SELECT * FROM arrangements WHERE id = ? AND user_id = ?",
        (arr_id, session["user_id"])
    ).fetchone()
    if not row:
        return jsonify({"error": "not found"}), 404

    if not row["venue_id"]:
        return jsonify({"error": "no venue assigned"}), 400

    venue_row = db.execute(
        "SELECT * FROM venues WHERE id = ?", (row["venue_id"],)
    ).fetchone()
    if not venue_row:
        return jsonify({"error": "venue not found"}), 404

    parts   = json.loads(row["participants_json"])
    constrs = json.loads(row["constraints_json"])

    if not parts:
        return jsonify({"error": "no participants defined"}), 400

    result, error = _run_csp(venue_row, parts, constrs)
    status      = "solved" if result else "infeasible"
    result_json = json.dumps(result) if result else json.dumps({"error": error})
    now         = datetime.utcnow().isoformat()

    db.execute(
        "UPDATE arrangements SET status=?, result_json=?, updated_at=? WHERE id=?",
        (status, result_json, now, arr_id)
    )
    db.commit()
    updated = db.execute("SELECT * FROM arrangements WHERE id = ?", (arr_id,)).fetchone()
    return jsonify(arrangement_to_api(updated))


@app.route("/api/arrangements/<int:arr_id>", methods=["DELETE"])
@login_required
def api_arrangement_delete(arr_id):
    db = get_db()
    existing = db.execute(
        "SELECT id FROM arrangements WHERE id = ? AND user_id = ?",
        (arr_id, session["user_id"])
    ).fetchone()
    if not existing:
        return jsonify({"error": "not found"}), 404
    db.execute("DELETE FROM arrangements WHERE id = ?", (arr_id,))
    db.commit()
    return jsonify({"deleted": arr_id})


@app.route("/api/arrangements/<int:arr_id>/export")
@login_required
def api_arrangement_export(arr_id):
    db  = get_db()
    row = db.execute(
        "SELECT * FROM arrangements WHERE id = ? AND user_id = ?",
        (arr_id, session["user_id"])
    ).fetchone()
    if not row:
        return jsonify({"error": "not found"}), 404

    payload  = arrangement_to_api(row)
    pretty   = json.dumps(payload, indent=2, ensure_ascii=False)
    safe     = "".join(c if c.isalnum() or c in "-_ " else "_" for c in row["name"])
    filename = f"arrangement_{safe.replace(' ','_')}.json"
    return Response(
        pretty,
        mimetype="application/json",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'}
    )


def _run_csp(venue_row, participants_data: list, constraints_data: list):
    """
    Bridge: run the CSP solver and return (result_dict, error_str).
    result_dict keys: assignment, violations, stats
    """
    try:
        layout      = build_csp_layout(venue_row)
        participants = build_csp_participants(participants_data)
        constraints  = build_csp_constraints(constraints_data)

        csp    = SeatingCSP(participants, layout, constraints)
        assign = csp.solve()

        if assign is None:
            return None, "No valid arrangement found. Check constraints and available seats."

        violations = csp._verify(assign)
        return {
            "assignment":  assign,                      # { name: seat_id }
            "violations":  violations,
            "solved_at":   datetime.utcnow().isoformat(),
            "stats": {
                "participants": len(participants_data),
                "seats_used":   len(assign),
                "violations":   len(violations),
            },
        }, None

    except ValueError as e:
        return None, str(e)
    except Exception as e:
        return None, f"Solver error: {e}"


# ── Entry point ───────────────────────────────────────────────────────────────

if __name__ == "__main__":
    init_db()
    print("\n  Smart Seating Planner — dev server")
    print("  → http://127.0.0.1:5000\n")
    app.run(debug=True, port=5000)
