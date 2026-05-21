"""
app.py
======
Application factory for the Smart Seating Layout Design and Planner.

Module layout
-------------
app.py            – factory + blueprint registration (this file)
database.py       – SQLite connection helpers and schema init
auth.py           – password hashing, login_required, /auth + /logout routes
dashboard.py      – / and /dashboard routes
venues.py         – venue pages + /api/venues* routes
participants.py   – participant roster page + /api/participants* routes
arrangements.py   – arrangement pages + /api/arrangements* routes
export_routes.py  – /export hub + all download endpoints
csp_bridge.py     – adapter between JSON data and seating_csp module
seating_csp.py    – CSP solver (AC-3 + backtracking, unchanged)
"""

import json
import os
import secrets

from flask import Flask

from database import close_db, init_db

# Blueprints
from auth import auth_bp
from dashboard import dashboard_bp
from venues import venues_bp
from participants import participants_bp
from arrangements import arrangements_bp
from export_routes import export_bp


def create_app() -> Flask:
    app = Flask(__name__)
    app.secret_key = os.environ.get("SECRET_KEY", secrets.token_hex(32))

    # Custom Jinja2 filter: parse a JSON string inside templates
    app.jinja_env.filters["from_json"] = json.loads

    # Tear-down: close DB connection after every request
    app.teardown_appcontext(close_db)

    # Register blueprints
    app.register_blueprint(auth_bp)
    app.register_blueprint(dashboard_bp)
    app.register_blueprint(venues_bp)
    app.register_blueprint(participants_bp)
    app.register_blueprint(arrangements_bp)
    app.register_blueprint(export_bp)

    # Health-check
    @app.route("/api/health")
    def health():
        from flask import jsonify
        return jsonify({"status": "ok", "version": "0.4.0"})

    return app


# ── Entry point ───────────────────────────────────────────────────────────────

if __name__ == "__main__":
    init_db()
    print("\n  Smart Seating Layout Design and Planner — dev server")
    print("  → http://127.0.0.1:5000\n")
    application = create_app()
    application.run(debug=True, port=5000)
