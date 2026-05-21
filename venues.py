"""
venues.py
=========
Venue layout management.

Exports
-------
venues_bp        – Flask Blueprint (registered in app.py)
build_layout_json – used by the API handlers
venue_to_api     – serialise a DB row to JSON-safe dict
"""

import json
from datetime import datetime

from flask import (
    Blueprint, Response, flash, jsonify,
    redirect, render_template, request, session, url_for,
)

from auth import login_required
from database import get_db

venues_bp = Blueprint("venues", __name__)


# ── Helpers ───────────────────────────────────────────────────────────────────

def compute_stats(seats: dict) -> dict:
    total     = len(seats)
    blocked   = sum(1 for s in seats.values() if s.get("is_blocked"))
    aisle     = sum(1 for s in seats.values() if s.get("is_aisle") and not s.get("is_blocked"))
    front     = sum(1 for s in seats.values() if s.get("is_front") and not s.get("is_blocked"))
    return {
        "total":     total,
        "available": total - blocked,
        "blocked":   blocked,
        "aisle":     aisle,
        "front":     front,
    }


def build_layout_json(
    rows: int,
    cols: int,
    seats_override: dict | None = None,
) -> dict:
    """
    Build the canonical venue JSON layout dict.

    If *seats_override* is supplied (e.g. from the venue editor's PUT payload),
    those seat states are merged in; otherwise every seat gets default values
    based on its position (front row, aisle columns).
    """
    seats: dict[str, dict] = {}
    for r in range(rows):
        for c in range(cols):
            sid      = f"R{r+1}C{c+1}"
            is_aisle = (c == 0 or c == cols - 1)
            is_front = (r == 0)
            default_type = "front" if is_front else ("aisle" if is_aisle else "normal")

            if seats_override and sid in seats_override:
                seat          = dict(seats_override[sid])
                seat["id"]    = sid
                seat["row"]   = r
                seat["col"]   = c
                seat["is_front"] = is_front
                seats[sid]    = seat
            else:
                seats[sid] = {
                    "id":         sid,
                    "row":        r,
                    "col":        c,
                    "type":       default_type,
                    "label":      "",
                    "is_blocked": False,
                    "is_aisle":   is_aisle,
                    "is_front":   is_front,
                }

    return {
        "schema_version": "1.0",
        "rows":  rows,
        "cols":  cols,
        "seats": seats,
        "stats": compute_stats(seats),
    }


def venue_to_api(row) -> dict:
    """Convert a SQLite Row to a JSON-serialisable dict."""
    return {
        "id":          row["id"],
        "name":        row["name"],
        "description": row["description"],
        "venue_type":  row["venue_type"],
        "rows":        row["rows"],
        "cols":        row["cols"],
        "layout":      json.loads(row["layout_json"]),
        "created_at":  row["created_at"],
        "updated_at":  row["updated_at"],
    }


# ── Page routes ───────────────────────────────────────────────────────────────

@venues_bp.route("/venues")
@login_required
def venues_list():
    db     = get_db()
    user   = db.execute("SELECT * FROM users WHERE id = ?", (session["user_id"],)).fetchone()
    venues = db.execute(
        "SELECT * FROM venues WHERE user_id = ? ORDER BY updated_at DESC",
        (session["user_id"],),
    ).fetchall()
    return render_template("venues.html", user=user, venues=venues)


@venues_bp.route("/venues/new")
@login_required
def venue_new():
    db   = get_db()
    user = db.execute("SELECT * FROM users WHERE id = ?", (session["user_id"],)).fetchone()
    return render_template("venue_editor.html", user=user, venue=None)


@venues_bp.route("/venues/<int:venue_id>/edit")
@login_required
def venue_edit(venue_id):
    db    = get_db()
    user  = db.execute("SELECT * FROM users WHERE id = ?", (session["user_id"],)).fetchone()
    venue = db.execute(
        "SELECT * FROM venues WHERE id = ? AND user_id = ?",
        (venue_id, session["user_id"]),
    ).fetchone()
    if not venue:
        flash("Venue not found.", "error")
        return redirect(url_for("venues.venues_list"))
    return render_template("venue_editor.html", user=user, venue=venue)


# ── JSON API routes ───────────────────────────────────────────────────────────

@venues_bp.route("/api/venues", methods=["GET"])
@login_required
def api_venues_list():
    db     = get_db()
    venues = db.execute(
        "SELECT * FROM venues WHERE user_id = ? ORDER BY updated_at DESC",
        (session["user_id"],),
    ).fetchall()
    return jsonify([venue_to_api(v) for v in venues])


@venues_bp.route("/api/venues", methods=["POST"])
@login_required
def api_venue_create():
    data        = request.get_json(silent=True) or {}
    name        = (data.get("name") or "").strip()
    description = (data.get("description") or "").strip()
    venue_type  = data.get("venue_type", "classroom")
    rows        = int(data.get("rows", 5))
    cols        = int(data.get("cols", 6))
    seats_data  = data.get("seats")

    if not name:
        return jsonify({"error": "name is required"}), 400
    if not (1 <= rows <= 30 and 1 <= cols <= 30):
        return jsonify({"error": "rows and cols must be between 1 and 30"}), 400

    now    = datetime.utcnow().isoformat()
    layout = build_layout_json(rows, cols, seats_override=seats_data)
    layout["metadata"] = {
        "created_at": now, "updated_at": now,
        "venue_type": venue_type, "name": name, "description": description,
    }

    db  = get_db()
    cur = db.execute(
        """INSERT INTO venues
           (user_id, name, description, venue_type, rows, cols, layout_json, created_at, updated_at)
           VALUES (?,?,?,?,?,?,?,?,?)""",
        (session["user_id"], name, description, venue_type,
         rows, cols, json.dumps(layout), now, now),
    )
    db.commit()
    venue = db.execute("SELECT * FROM venues WHERE id = ?", (cur.lastrowid,)).fetchone()
    return jsonify(venue_to_api(venue)), 201


@venues_bp.route("/api/venues/<int:venue_id>", methods=["GET"])
@login_required
def api_venue_get(venue_id):
    db    = get_db()
    venue = db.execute(
        "SELECT * FROM venues WHERE id = ? AND user_id = ?",
        (venue_id, session["user_id"]),
    ).fetchone()
    if not venue:
        return jsonify({"error": "not found"}), 404
    return jsonify(venue_to_api(venue))


@venues_bp.route("/api/venues/<int:venue_id>", methods=["PUT"])
@login_required
def api_venue_update(venue_id):
    db    = get_db()
    venue = db.execute(
        "SELECT * FROM venues WHERE id = ? AND user_id = ?",
        (venue_id, session["user_id"]),
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

    now        = datetime.utcnow().isoformat()
    old_meta   = json.loads(venue["layout_json"]).get("metadata") or {}
    layout     = build_layout_json(rows, cols, seats_override=seats_data)
    layout["metadata"] = {
        **old_meta,
        "updated_at": now, "venue_type": venue_type,
        "name": name, "description": description,
    }

    db.execute(
        """UPDATE venues
           SET name=?, description=?, venue_type=?, rows=?, cols=?, layout_json=?, updated_at=?
           WHERE id=?""",
        (name, description, venue_type, rows, cols, json.dumps(layout), now, venue_id),
    )
    db.commit()
    updated = db.execute("SELECT * FROM venues WHERE id = ?", (venue_id,)).fetchone()
    return jsonify(venue_to_api(updated))


@venues_bp.route("/api/venues/<int:venue_id>", methods=["DELETE"])
@login_required
def api_venue_delete(venue_id):
    db  = get_db()
    row = db.execute(
        "SELECT id FROM venues WHERE id = ? AND user_id = ?",
        (venue_id, session["user_id"]),
    ).fetchone()
    if not row:
        return jsonify({"error": "not found"}), 404
    db.execute("DELETE FROM venues WHERE id = ?", (venue_id,))
    db.commit()
    return jsonify({"deleted": venue_id})


@venues_bp.route("/api/venues/<int:venue_id>/export")
@login_required
def api_venue_export(venue_id):
    db    = get_db()
    venue = db.execute(
        "SELECT * FROM venues WHERE id = ? AND user_id = ?",
        (venue_id, session["user_id"]),
    ).fetchone()
    if not venue:
        return jsonify({"error": "not found"}), 404

    pretty    = json.dumps(venue_to_api(venue), indent=2, ensure_ascii=False)
    safe_name = "".join(c if c.isalnum() or c in "-_ " else "_" for c in venue["name"])
    filename  = f"venue_{safe_name.replace(' ', '_')}.json"
    return Response(
        pretty,
        mimetype="application/json",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )
