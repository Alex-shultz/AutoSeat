"""
auth.py
=======
Password hashing, login_required decorator, and auth routes
(sign-in, register, logout).
"""

import hashlib
import secrets
from datetime import datetime
from functools import wraps

from flask import (
    Blueprint, flash, redirect, render_template,
    request, session, url_for,
)

from database import get_db

auth_bp = Blueprint("auth", __name__)


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
            return redirect(url_for("auth.auth_page"))
        return f(*args, **kwargs)
    return decorated


# ── Routes ────────────────────────────────────────────────────────────────────

@auth_bp.route("/auth", methods=["GET", "POST"])
def auth_page():
    if "user_id" in session:
        return redirect(url_for("dashboard.dashboard"))

    if request.method == "POST":
        action = request.form.get("action")

        if action == "login":
            identifier = request.form.get("identifier", "").strip()
            password   = request.form.get("password", "")
            db   = get_db()
            user = db.execute(
                "SELECT * FROM users WHERE username = ? OR email = ?",
                (identifier, identifier),
            ).fetchone()
            if user and verify_password(password, user["password"]):
                session.permanent = True
                session["user_id"]  = user["id"]
                session["username"] = user["username"]
                session["role"]     = user["role"]
                return redirect(url_for("dashboard.dashboard"))
            flash("Invalid credentials. Please try again.", "error")
            return redirect(url_for("auth.auth_page") + "?tab=login")

        elif action == "register":
            username = request.form.get("username", "").strip()
            email    = request.form.get("email", "").strip().lower()
            password = request.form.get("password", "")
            confirm  = request.form.get("confirm", "")

            if len(username) < 3:
                flash("Username must be at least 3 characters.", "error")
                return redirect(url_for("auth.auth_page") + "?tab=register")
            if len(password) < 8:
                flash("Password must be at least 8 characters.", "error")
                return redirect(url_for("auth.auth_page") + "?tab=register")
            if password != confirm:
                flash("Passwords do not match.", "error")
                return redirect(url_for("auth.auth_page") + "?tab=register")

            db = get_db()
            try:
                db.execute(
                    "INSERT INTO users (username, email, password, role, created_at)"
                    " VALUES (?,?,?,?,?)",
                    (username, email, hash_password(password), "planner",
                     datetime.utcnow().isoformat()),
                )
                db.commit()
                flash("Account created! You can now log in.", "success")
                return redirect(url_for("auth.auth_page") + "?tab=login")
            except Exception:
                flash("Username or email already taken.", "error")
                return redirect(url_for("auth.auth_page") + "?tab=register")

    active_tab = request.args.get("tab", "login")
    return render_template("auth.html", active_tab=active_tab)


@auth_bp.route("/logout", methods=["POST"])
def logout():
    session.clear()
    flash("You've been logged out.", "info")
    return redirect(url_for("auth.auth_page"))
