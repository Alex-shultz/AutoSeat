"""
export_routes.py
================
Export hub page + download endpoints (JSON, CSV, PNG, JPEG).
"""

import csv
import io
import json
from datetime import datetime

from flask import Blueprint, Response, jsonify, render_template, session

from auth import login_required
from database import get_db

export_bp = Blueprint("export_routes", __name__)


# ── Hub page ──────────────────────────────────────────────────────────────────

@export_bp.route("/export")
@login_required
def export_hub():
    db  = get_db()
    uid = session["user_id"]

    user   = db.execute("SELECT * FROM users WHERE id = ?", (uid,)).fetchone()
    venues = db.execute(
        "SELECT id, name, rows, cols, venue_type, updated_at"
        " FROM venues WHERE user_id = ? ORDER BY name",
        (uid,),
    ).fetchall()
    arrangements = db.execute(
        """SELECT a.id, a.name, a.status, a.updated_at, a.participants_json,
                  a.constraints_json, a.result_json, v.name as venue_name
           FROM arrangements a
           LEFT JOIN venues v ON a.venue_id = v.id
           WHERE a.user_id = ? ORDER BY a.name""",
        (uid,),
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


# ── Participants ──────────────────────────────────────────────────────────────

@export_bp.route("/api/export/participants.json")
@login_required
def export_participants_json():
    db   = get_db()
    rows = db.execute(
        "SELECT * FROM participants WHERE user_id = ? ORDER BY name",
        (session["user_id"],),
    ).fetchall()
    payload = {
        "exported_at":  datetime.utcnow().isoformat(),
        "count":        len(rows),
        "participants": [dict(r) for r in rows],
    }
    return Response(
        json.dumps(payload, indent=2),
        mimetype="application/json",
        headers={"Content-Disposition": 'attachment; filename="participants.json"'},
    )


@export_bp.route("/api/export/participants.csv")
@login_required
def export_participants_csv():
    db   = get_db()
    rows = db.execute(
        "SELECT name, group_name, needs_front_row, needs_aisle, notes, created_at"
        " FROM participants WHERE user_id = ? ORDER BY name",
        (session["user_id"],),
    ).fetchall()
    buf = io.StringIO()
    w   = csv.writer(buf)
    w.writerow(["name", "group", "needs_front_row", "needs_aisle", "notes", "created_at"])
    for r in rows:
        w.writerow([
            r["name"], r["group_name"],
            "yes" if r["needs_front_row"] else "no",
            "yes" if r["needs_aisle"]     else "no",
            r["notes"], r["created_at"],
        ])
    return Response(
        buf.getvalue(),
        mimetype="text/csv",
        headers={"Content-Disposition": 'attachment; filename="participants.csv"'},
    )


# ── Arrangements ──────────────────────────────────────────────────────────────

@export_bp.route("/api/export/arrangements/<int:arr_id>/assignment.csv")
@login_required
def export_arrangement_csv(arr_id):
    db  = get_db()
    row = db.execute(
        "SELECT * FROM arrangements WHERE id = ? AND user_id = ?",
        (arr_id, session["user_id"]),
    ).fetchone()
    if not row:
        return jsonify({"error": "not found"}), 404

    parts  = json.loads(row["participants_json"])
    result = json.loads(row["result_json"]) if row["result_json"] else {}
    assign = result.get("assignment", {})
    p_map  = {p["name"]: p for p in parts}

    buf = io.StringIO()
    w   = csv.writer(buf)
    w.writerow(["participant", "group", "seat", "row", "col",
                "needs_front_row", "needs_aisle", "status"])

    if assign:
        for name, seat_id in sorted(assign.items()):
            p = p_map.get(name, {})
            try:
                row_n, col_n = seat_id.replace("R", "").split("C")
            except Exception:
                row_n = col_n = ""
            w.writerow([
                name,
                p.get("group") or p.get("group_name") or "",
                seat_id, row_n, col_n,
                "yes" if p.get("needs_front_row") else "no",
                "yes" if p.get("needs_aisle")     else "no",
                row["status"],
            ])
    else:
        for p in parts:
            w.writerow([
                p["name"],
                p.get("group") or p.get("group_name") or "",
                "", "", "",
                "yes" if p.get("needs_front_row") else "no",
                "yes" if p.get("needs_aisle")     else "no",
                row["status"],
            ])

    safe  = "".join(c if c.isalnum() or c in "-_ " else "_" for c in row["name"])
    fname = f"arrangement_{safe.replace(' ', '_')}_assignment.csv"
    return Response(
        buf.getvalue(),
        mimetype="text/csv",
        headers={"Content-Disposition": f'attachment; filename="{fname}"'},
    )


# ── Image export (PNG / JPEG) ─────────────────────────────────────────────────

def _build_seating_image(row, fmt: str):
    """Render a seating chart with Pillow. Returns (bytes, mimetype, filename)."""
    from PIL import Image, ImageDraw, ImageFont

    parts      = json.loads(row["participants_json"])
    result     = json.loads(row["result_json"]) if row["result_json"] else {}
    assign     = result.get("assignment", {})
    p_map      = {p["name"]: p for p in parts}

    db        = get_db()
    venue_row = (
        db.execute("SELECT * FROM venues WHERE id = ?", (row["venue_id"],)).fetchone()
        if row["venue_id"] else None
    )
    if venue_row:
        layout      = json.loads(venue_row["layout_json"])
        grid_rows   = venue_row["rows"]
        grid_cols   = venue_row["cols"]
        seats_meta  = layout.get("seats", {})
    else:
        if assign:
            ids       = list(assign.values())
            grid_rows = max(int(s.split("C")[0][1:]) for s in ids)
            grid_cols = max(int(s.split("C")[1])     for s in ids)
        else:
            grid_rows = grid_cols = 1
        seats_meta = {}

    GROUP_PALETTE = [
        (240,165,0),(59,130,246),(34,197,94),(168,85,247),
        (236,72,153),(249,115,22),(20,184,166),(239,68,68),
    ]
    groups      = sorted({p.get("group") or p.get("group_name") or ""
                          for p in parts if p.get("group") or p.get("group_name")})
    group_color = {g: GROUP_PALETTE[i % len(GROUP_PALETTE)] for i, g in enumerate(groups)}

    CELL   = 80
    GAP    = 6
    MARGIN = 48
    HDR    = 56
    LABEL_W = 34

    W = MARGIN + LABEL_W + grid_cols * (CELL + GAP) - GAP + MARGIN
    H = HDR + MARGIN + grid_rows * (CELL + GAP) - GAP + MARGIN

    BG     = (11, 14, 20)
    PANEL  = (22, 28, 44)
    BORDER = (31, 43, 69)
    TEXT   = (232, 236, 244)
    MUTED  = (107, 122, 155)

    img  = Image.new("RGB", (W, H), BG)
    draw = ImageDraw.Draw(img)

    try:
        font_sm   = ImageFont.truetype("/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf", 11)
        font_bold = ImageFont.truetype("/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf", 11)
        font_name = ImageFont.truetype("/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf", 10)
    except Exception:
        font_sm = font_bold = font_name = ImageFont.load_default()

    draw.text((MARGIN, 14), row["name"], font=font_bold, fill=TEXT)
    status_color = (34,197,94) if row["status"]=="solved" else \
                   (239,68,68) if row["status"]=="infeasible" else (240,165,0)
    draw.text((MARGIN, 34),
              f"Status: {row['status'].upper()}  ·  {len(assign)}/{len(parts)} seated",
              font=font_sm, fill=status_color)

    for c in range(grid_cols):
        cx = MARGIN + LABEL_W + c*(CELL+GAP) + CELL//2
        draw.text((cx, HDR-14), f"C{c+1}", font=font_sm, fill=MUTED, anchor="mm")

    seat_to_name = {v: k for k, v in assign.items()}

    for r in range(grid_rows):
        ry = HDR + MARGIN//2 + r*(CELL+GAP)
        draw.text((MARGIN+LABEL_W-6, ry+CELL//2), f"R{r+1}",
                  font=font_sm, fill=MUTED, anchor="rm")
        for c in range(grid_cols):
            sid   = f"R{r+1}C{c+1}"
            smeta = seats_meta.get(sid, {})
            x0, y0 = MARGIN+LABEL_W+c*(CELL+GAP), ry
            x1, y1 = x0+CELL, y0+CELL
            radius  = 6

            if smeta.get("is_blocked") or smeta.get("type") == "blocked":
                draw.rounded_rectangle([x0,y0,x1,y1], radius=radius,
                                       fill=(13,16,23), outline=BORDER)
                draw.line([x0+12,y0+12,x1-12,y1-12], fill=MUTED, width=2)
                draw.line([x1-12,y0+12,x0+12,y1-12], fill=MUTED, width=2)
            elif sid in seat_to_name:
                pname = seat_to_name[sid]
                p     = p_map.get(pname, {})
                color = group_color.get(p.get("group") or p.get("group_name") or "",
                                        (59,130,246))
                bg    = tuple(max(0, v-180) for v in color)
                draw.rounded_rectangle([x0,y0,x1,y1], radius=radius,
                                       fill=bg, outline=color, width=2)
                draw.rounded_rectangle([x0,y0,x1,y0+4], radius=2, fill=color)
                short = pname if len(pname)<=10 else pname[:9]+"…"
                draw.text((x0+CELL//2, y0+CELL//2), short,
                          font=font_name, fill=TEXT, anchor="mm")
            else:
                oc = (59,80,150) if smeta.get("is_front") else \
                     (30,90,60)  if smeta.get("is_aisle") else BORDER
                draw.rounded_rectangle([x0,y0,x1,y1], radius=radius,
                                       fill=PANEL, outline=oc)

    # Legend
    leg_x, leg_y = MARGIN, HDR+MARGIN//2+grid_rows*(CELL+GAP)+8
    if leg_y+20 < H and groups:
        draw.text((leg_x, leg_y), "Groups: ", font=font_sm, fill=MUTED)
        leg_x += 55
        for g in groups[:6]:
            c = group_color.get(g, (100,100,100))
            draw.rectangle([leg_x, leg_y+2, leg_x+10, leg_y+12], fill=c)
            draw.text((leg_x+14, leg_y), g, font=font_sm, fill=MUTED)
            leg_x += 14 + len(g)*7 + 10

    buf = io.BytesIO()
    if fmt == "jpeg":
        img.save(buf, format="JPEG", quality=92, optimize=True)
        mime = "image/jpeg"
    else:
        img.save(buf, format="PNG", optimize=True)
        mime = "image/png"
    buf.seek(0)

    safe  = "".join(ch if ch.isalnum() or ch in "-_ " else "_" for ch in row["name"])
    fname = f"arrangement_{safe.replace(' ','_')}.{fmt}"
    return buf.getvalue(), mime, fname


@export_bp.route("/api/export/arrangements/<int:arr_id>/image.<fmt>")
@login_required
def export_arrangement_image(arr_id, fmt):
    if fmt not in ("png", "jpeg", "jpg"):
        return jsonify({"error": "unsupported format — use png or jpeg"}), 400
    if fmt == "jpg":
        fmt = "jpeg"

    db  = get_db()
    row = db.execute(
        "SELECT * FROM arrangements WHERE id = ? AND user_id = ?",
        (arr_id, session["user_id"]),
    ).fetchone()
    if not row:
        return jsonify({"error": "not found"}), 404
    if not row["result_json"]:
        return jsonify({"error": "arrangement has not been solved yet"}), 400

    data, mime, fname = _build_seating_image(row, fmt)
    return Response(
        data,
        mimetype=mime,
        headers={"Content-Disposition": f'attachment; filename="{fname}"'},
    )
