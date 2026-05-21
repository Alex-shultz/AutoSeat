"""
csp_bridge.py
=============
Adapter layer between the web application's JSON data structures
and the seating_csp module's dataclasses.

Provides:
  build_csp_layout()        – venue DB row → GridLayout
  build_csp_participants()  – list of dicts  → list[Participant]
  build_csp_constraints()   – list of dicts  → list[Constraint]
  run_csp()                 – run solver, return (result_dict, error_str)
"""

import json
from datetime import datetime

from seating_csp import (
    Constraint,
    ConstraintType,
    GridLayout,
    Participant,
    SeatingCSP,
)


# ── Mapping from JSON string → ConstraintType ─────────────────────────────────

_CTYPE_MAP: dict[str, ConstraintType] = {
    "MUST_SIT_TOGETHER":     ConstraintType.MUST_SIT_TOGETHER,
    "MUST_NOT_SIT_TOGETHER": ConstraintType.MUST_NOT_SIT_TOGETHER,
    "SAME_GROUP_TOGETHER":   ConstraintType.SAME_GROUP_TOGETHER,
    "SAME_GROUP_APART":      ConstraintType.SAME_GROUP_APART,
    "FRONT_ROW":             ConstraintType.FRONT_ROW,
    "NEAR_AISLE":            ConstraintType.NEAR_AISLE,
    "SPECIFIC_SEAT":         ConstraintType.SPECIFIC_SEAT,
    "RESERVED_SEAT":         ConstraintType.RESERVED_SEAT,
}


# ── Builders ──────────────────────────────────────────────────────────────────

def build_csp_layout(venue_row) -> GridLayout:
    """Convert a SQLite venue row into a GridLayout."""
    layout = json.loads(venue_row["layout_json"])
    seats  = layout.get("seats", {})
    rows   = venue_row["rows"]
    cols   = venue_row["cols"]

    blocked = [
        sid for sid, s in seats.items()
        if s.get("is_blocked") or s.get("type") == "blocked"
    ]
    aisle_cols_set: set[int] = set()
    for s in seats.values():
        if s.get("is_aisle") or s.get("type") == "aisle":
            aisle_cols_set.add(s["col"])  # 0-based

    return GridLayout(
        rows=rows,
        cols=cols,
        blocked_seats=blocked,
        aisle_cols=list(aisle_cols_set) if aisle_cols_set else None,
    )


def build_csp_participants(participants_data: list) -> list[Participant]:
    """Convert a list of participant dicts into Participant dataclasses."""
    return [
        Participant(
            name=p["name"],
            group=p.get("group") or None,
            needs_front_row=bool(p.get("needs_front_row")),
            needs_aisle=bool(p.get("needs_aisle")),
            reserved_seat=p.get("reserved_seat") or None,
        )
        for p in participants_data
    ]


def build_csp_constraints(constraints_data: list) -> list[Constraint]:
    """Convert a list of constraint dicts into Constraint dataclasses."""
    result = []
    for c in constraints_data:
        ctype = _CTYPE_MAP.get(c.get("type", ""))
        if not ctype:
            continue
        result.append(
            Constraint(
                constraint_type=ctype,
                participants=c.get("participants", []),
                group=c.get("group") or None,
                seat_id=c.get("seat_id") or None,
            )
        )
    return result


# ── Solver entry point ────────────────────────────────────────────────────────

def run_csp(
    venue_row,
    participants_data: list,
    constraints_data: list,
) -> tuple[dict | None, str | None]:
    """
    Build CSP objects from JSON data, run the solver, and return
    (result_dict, error_str).  Exactly one of the two is non-None.

    result_dict keys
    ----------------
    assignment : dict[name, seat_id]
    violations : list[str]
    solved_at  : ISO timestamp
    stats      : dict
    """
    try:
        layout       = build_csp_layout(venue_row)
        participants = build_csp_participants(participants_data)
        constraints  = build_csp_constraints(constraints_data)

        csp    = SeatingCSP(participants, layout, constraints)
        assign = csp.solve()

        if assign is None:
            return None, (
                "No valid arrangement found. "
                "Check that constraints are not contradictory and that "
                "enough seats are available."
            )

        violations = csp._verify(assign)
        return {
            "assignment": assign,
            "violations": violations,
            "solved_at":  datetime.utcnow().isoformat(),
            "stats": {
                "participants": len(participants_data),
                "seats_used":   len(assign),
                "violations":   len(violations),
            },
        }, None

    except ValueError as exc:
        return None, str(exc)
    except Exception as exc:
        return None, f"Solver error: {exc}"
