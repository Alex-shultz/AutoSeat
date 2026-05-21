"""
dashboard.py
============
Dashboard and root redirect routes.
"""

import json

from flask import Blueprint, redirect, render_template, session, url_for

from auth import login_required
from database import get_db

dashboard_bp = Blueprint("dashboard", __name__)


@dashboard_bp.route("/")
def index():
    if "user_id" in session:
        return redirect(url_for("dashboard.dashboard"))
    return redirect(url_for("auth.auth_page"))


@dashboard_bp.route("/dashboard")
@login_required
def dashboard():
    db  = get_db()
    uid = session["user_id"]

    user        = db.execute("SELECT * FROM users WHERE id = ?", (uid,)).fetchone()
    venue_count = db.execute(
        "SELECT COUNT(*) as cnt FROM venues WHERE user_id = ?", (uid,)
    ).fetchone()["cnt"]
    arrangement_count = db.execute(
        "SELECT COUNT(*) as cnt FROM arrangements WHERE user_id = ?", (uid,)
    ).fetchone()["cnt"]
    solved_count = db.execute(
        "SELECT COUNT(*) as cnt FROM arrangements WHERE user_id = ? AND status = 'solved'",
        (uid,),
    ).fetchone()["cnt"]

    all_parts = db.execute(
        "SELECT participants_json FROM arrangements WHERE user_id = ?", (uid,)
    ).fetchall()
    participant_total = sum(len(json.loads(r["participants_json"])) for r in all_parts)

    recent = db.execute(
        """SELECT a.*, v.name as venue_name
           FROM arrangements a
           LEFT JOIN venues v ON a.venue_id = v.id
           WHERE a.user_id = ?
           ORDER BY a.updated_at DESC LIMIT 5""",
        (uid,),
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
