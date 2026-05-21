"""
arrangements.py
===============
Seating arrangement management — page routes, JSON API, and CSP solver trigger.
"""

import json
from datetime import datetime

from flask import (
    Blueprint, Response, flash, jsonify,
    redirect, render_template, request, session, url_for,
)

from auth import login_required
from csp_bridge import run_csp
from database import get_db

arrangements_bp = Blueprint("arrangements", __name__)


# ── Helpers ───────────────────────────────────────────────────────────────────

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


# ── Page routes ───────────────────────────────────────────────────────────────

@arrangements_bp.route("/arrangements")
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
        (session["user_id"],),
    ).fetchall()
    return render_template("arrangements.html", user=user, arrangements=rows)


@arrangements_bp.route("/arrangements/new")
@login_required
def arrangement_new():
    db     = get_db()
    user   = db.execute("SELECT * FROM users WHERE id = ?", (session["user_id"],)).fetchone()
    venues = db.execute(
        "SELECT id, name, rows, cols FROM venues WHERE user_id = ? ORDER BY name",
        (session["user_id"],),
    ).fetchall()
    return render_template("arrangement_editor.html", user=user,
                           arrangement=None, venues=venues)


@arrangements_bp.route("/arrangements/<int:arr_id>")
@login_required
def arrangement_view(arr_id):
    db   = get_db()
    user = db.execute("SELECT * FROM users WHERE id = ?", (session["user_id"],)).fetchone()
    row  = db.execute(
        "SELECT * FROM arrangements WHERE id = ? AND user_id = ?",
        (arr_id, session["user_id"]),
    ).fetchone()
    if not row:
        flash("Arrangement not found.", "error")
        return redirect(url_for("arrangements.arrangements_list"))

    venues = db.execute(
        "SELECT id, name, rows, cols FROM venues WHERE user_id = ? ORDER BY name",
        (session["user_id"],),
    ).fetchall()
    venue = None
    if row["venue_id"]:
        venue = db.execute(
            "SELECT * FROM venues WHERE id = ?", (row["venue_id"],)
        ).fetchone()
    return render_template("arrangement_editor.html", user=user,
                           arrangement=row, venues=venues, venue=venue)


# ── JSON API routes ───────────────────────────────────────────────────────────

@arrangements_bp.route("/api/arrangements", methods=["GET"])
@login_required
def api_arrangements_list():
    db   = get_db()
    rows = db.execute(
        "SELECT * FROM arrangements WHERE user_id = ? ORDER BY updated_at DESC",
        (session["user_id"],),
    ).fetchall()
    return jsonify([arrangement_to_api(r) for r in rows])


@arrangements_bp.route("/api/arrangements", methods=["POST"])
@login_required
def api_arrangement_create():
    data     = request.get_json(silent=True) or {}
    name     = (data.get("name") or "").strip()
    venue_id = data.get("venue_id")
    parts    = data.get("participants", [])
    constrs  = data.get("constraints", [])

    if not name:
        return jsonify({"error": "name is required"}), 400

    db        = get_db()
    venue_row = None
    if venue_id:
        venue_row = db.execute(
            "SELECT * FROM venues WHERE id = ? AND user_id = ?",
            (venue_id, session["user_id"]),
        ).fetchone()
        if not venue_row:
            return jsonify({"error": "venue not found"}), 404

    now = datetime.utcnow().isoformat()
    cur = db.execute(
        """INSERT INTO arrangements
           (user_id, venue_id, name, status, participants_json, constraints_json,
            result_json, created_at, updated_at)
           VALUES (?,?,?,?,?,?,NULL,?,?)""",
        (session["user_id"], venue_id, name, "unsolved",
         json.dumps(parts), json.dumps(constrs), now, now),
    )
    db.commit()
    arr_id = cur.lastrowid

    # Optionally solve immediately
    if data.get("solve") and venue_row and parts:
        result, error = run_csp(venue_row, parts, constrs)
        status      = "solved" if result else "infeasible"
        result_json = json.dumps(result if result else {"error": error})
        db.execute(
            "UPDATE arrangements SET status=?, result_json=?, updated_at=? WHERE id=?",
            (status, result_json, datetime.utcnow().isoformat(), arr_id),
        )
        db.commit()

    row = db.execute("SELECT * FROM arrangements WHERE id = ?", (arr_id,)).fetchone()
    return jsonify(arrangement_to_api(row)), 201


@arrangements_bp.route("/api/arrangements/<int:arr_id>", methods=["PUT"])
@login_required
def api_arrangement_update(arr_id):
    db  = get_db()
    row = db.execute(
        "SELECT * FROM arrangements WHERE id = ? AND user_id = ?",
        (arr_id, session["user_id"]),
    ).fetchone()
    if not row:
        return jsonify({"error": "not found"}), 404

    data    = request.get_json(silent=True) or {}
    name    = (data.get("name") or row["name"]).strip()
    vid     = data.get("venue_id", row["venue_id"])
    parts   = data.get("participants", json.loads(row["participants_json"]))
    constrs = data.get("constraints",  json.loads(row["constraints_json"]))
    now     = datetime.utcnow().isoformat()

    db.execute(
        """UPDATE arrangements
           SET name=?, venue_id=?, participants_json=?, constraints_json=?, updated_at=?
           WHERE id=?""",
        (name, vid, json.dumps(parts), json.dumps(constrs), now, arr_id),
    )
    db.commit()
    updated = db.execute("SELECT * FROM arrangements WHERE id = ?", (arr_id,)).fetchone()
    return jsonify(arrangement_to_api(updated))


@arrangements_bp.route("/api/arrangements/<int:arr_id>/solve", methods=["POST"])
@login_required
def api_arrangement_solve(arr_id):
    db  = get_db()
    row = db.execute(
        "SELECT * FROM arrangements WHERE id = ? AND user_id = ?",
        (arr_id, session["user_id"]),
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

    result, error = run_csp(venue_row, parts, constrs)
    status      = "solved" if result else "infeasible"
    result_json = json.dumps(result if result else {"error": error})
    now         = datetime.utcnow().isoformat()

    db.execute(
        "UPDATE arrangements SET status=?, result_json=?, updated_at=? WHERE id=?",
        (status, result_json, now, arr_id),
    )
    db.commit()
    updated = db.execute("SELECT * FROM arrangements WHERE id = ?", (arr_id,)).fetchone()
    return jsonify(arrangement_to_api(updated))


@arrangements_bp.route("/api/arrangements/<int:arr_id>", methods=["DELETE"])
@login_required
def api_arrangement_delete(arr_id):
    db  = get_db()
    row = db.execute(
        "SELECT id FROM arrangements WHERE id = ? AND user_id = ?",
        (arr_id, session["user_id"]),
    ).fetchone()
    if not row:
        return jsonify({"error": "not found"}), 404
    db.execute("DELETE FROM arrangements WHERE id = ?", (arr_id,))
    db.commit()
    return jsonify({"deleted": arr_id})


@arrangements_bp.route("/api/arrangements/<int:arr_id>/export")
@login_required
def api_arrangement_export(arr_id):
    db  = get_db()
    row = db.execute(
        "SELECT * FROM arrangements WHERE id = ? AND user_id = ?",
        (arr_id, session["user_id"]),
    ).fetchone()
    if not row:
        return jsonify({"error": "not found"}), 404

    pretty   = json.dumps(arrangement_to_api(row), indent=2, ensure_ascii=False)
    safe     = "".join(c if c.isalnum() or c in "-_ " else "_" for c in row["name"])
    filename = f"arrangement_{safe.replace(' ', '_')}.json"
    return Response(
        pretty,
        mimetype="application/json",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )
