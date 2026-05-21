"""
participants.py
===============
Global participant roster — page and JSON API routes.
"""

import sqlite3
from datetime import datetime

from flask import (
    Blueprint, jsonify, redirect, render_template,
    request, session, url_for,
)

from auth import login_required
from database import get_db

participants_bp = Blueprint("participants", __name__)


# ── Page ──────────────────────────────────────────────────────────────────────

@participants_bp.route("/participants")
@login_required
def participants_list():
    db   = get_db()
    user = db.execute("SELECT * FROM users WHERE id = ?", (session["user_id"],)).fetchone()
    rows = db.execute(
        "SELECT * FROM participants WHERE user_id = ? ORDER BY name ASC",
        (session["user_id"],),
    ).fetchall()
    return render_template("participants.html", user=user,
                           participants=[dict(r) for r in rows])


# ── JSON API ──────────────────────────────────────────────────────────────────

@participants_bp.route("/api/participants", methods=["GET"])
@login_required
def api_participants_list():
    db   = get_db()
    rows = db.execute(
        "SELECT * FROM participants WHERE user_id = ? ORDER BY name ASC",
        (session["user_id"],),
    ).fetchall()
    return jsonify([dict(r) for r in rows])


@participants_bp.route("/api/participants", methods=["POST"])
@login_required
def api_participant_create():
    data = request.get_json(silent=True) or {}
    name = (data.get("name") or "").strip()
    if not name:
        return jsonify({"error": "name is required"}), 400

    now = datetime.utcnow().isoformat()
    db  = get_db()
    try:
        cur = db.execute(
            """INSERT INTO participants
               (user_id, name, group_name, needs_front_row, needs_aisle, notes, created_at)
               VALUES (?,?,?,?,?,?,?)""",
            (
                session["user_id"],
                name,
                (data.get("group_name") or "").strip(),
                1 if data.get("needs_front_row") else 0,
                1 if data.get("needs_aisle")     else 0,
                (data.get("notes") or "").strip(),
                now,
            ),
        )
        db.commit()
        row = db.execute("SELECT * FROM participants WHERE id = ?", (cur.lastrowid,)).fetchone()
        return jsonify(dict(row)), 201
    except sqlite3.IntegrityError:
        return jsonify({"error": f"A participant named '{name}' already exists."}), 409


@participants_bp.route("/api/participants/<int:pid>", methods=["PUT"])
@login_required
def api_participant_update(pid):
    db  = get_db()
    row = db.execute(
        "SELECT * FROM participants WHERE id = ? AND user_id = ?",
        (pid, session["user_id"]),
    ).fetchone()
    if not row:
        return jsonify({"error": "not found"}), 404

    data = request.get_json(silent=True) or {}
    name = (data.get("name") or row["name"]).strip()
    if not name:
        return jsonify({"error": "name is required"}), 400

    try:
        db.execute(
            """UPDATE participants
               SET name=?, group_name=?, needs_front_row=?, needs_aisle=?, notes=?
               WHERE id=?""",
            (
                name,
                (data.get("group_name", row["group_name"]) or "").strip(),
                1 if data.get("needs_front_row") else 0,
                1 if data.get("needs_aisle")     else 0,
                (data.get("notes", row["notes"]) or "").strip(),
                pid,
            ),
        )
        db.commit()
        updated = db.execute("SELECT * FROM participants WHERE id = ?", (pid,)).fetchone()
        return jsonify(dict(updated))
    except sqlite3.IntegrityError:
        return jsonify({"error": f"A participant named '{name}' already exists."}), 409


@participants_bp.route("/api/participants/<int:pid>", methods=["DELETE"])
@login_required
def api_participant_delete(pid):
    db  = get_db()
    row = db.execute(
        "SELECT id FROM participants WHERE id = ? AND user_id = ?",
        (pid, session["user_id"]),
    ).fetchone()
    if not row:
        return jsonify({"error": "not found"}), 404
    db.execute("DELETE FROM participants WHERE id = ?", (pid,))
    db.commit()
    return jsonify({"deleted": pid})
