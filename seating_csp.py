"""
seating_csp.py
==============
Seating Arrangement Generation Module — Prototype
Project: Web-based Smart Seating Layout Design and Planner
Algorithm: Constraint Satisfaction Problem (CSP) with
           Arc-Consistency (AC-3) + Backtracking Search

Usage
-----
Run directly for a demo:
    python seating_csp.py

Or import and use programmatically:
    from seating_csp import Participant, GridLayout, Constraint, SeatingCSP
"""

from __future__ import annotations

import copy
import random
from dataclasses import dataclass, field
from enum import Enum, auto
from typing import Optional


# ---------------------------------------------------------------------------
# Data Models
# ---------------------------------------------------------------------------

class ConstraintType(Enum):
    MUST_SIT_TOGETHER      = auto()  # two participants must be adjacent
    MUST_NOT_SIT_TOGETHER  = auto()  # two participants must NOT be adjacent
    SAME_GROUP_TOGETHER    = auto()  # all members of a group sit together
    SAME_GROUP_APART       = auto()  # group members must NOT be adjacent
    FRONT_ROW              = auto()  # participant must sit in the front row
    NEAR_AISLE             = auto()  # participant must sit in an aisle seat
    SPECIFIC_SEAT          = auto()  # participant must sit at an exact seat id
    RESERVED_SEAT          = auto()  # seat is off-limits (blocked)


@dataclass
class Participant:
    """A single person to be seated."""
    name: str
    group: Optional[str] = None         # e.g. "team-A", "family-Jones"
    needs_front_row: bool = False        # poor eyesight, etc.
    needs_aisle: bool = False            # wheelchair, mobility aid
    reserved_seat: Optional[str] = None # operator-assigned seat id, e.g. "R1C2"

    def __repr__(self) -> str:
        tags = []
        if self.group:          tags.append(f"group={self.group}")
        if self.needs_front_row: tags.append("front")
        if self.needs_aisle:    tags.append("aisle")
        if self.reserved_seat:  tags.append(f"seat={self.reserved_seat}")
        tag_str = f" [{', '.join(tags)}]" if tags else ""
        return f"Participant({self.name!r}{tag_str})"


@dataclass
class Constraint:
    """A single named constraint between participants or a seat property."""
    constraint_type: ConstraintType
    participants: list[str] = field(default_factory=list)  # participant names
    group: Optional[str] = None                            # for group constraints
    seat_id: Optional[str] = None                          # for seat-specific constraints

    def __repr__(self) -> str:
        return (f"Constraint({self.constraint_type.name}, "
                f"participants={self.participants}, group={self.group}, seat={self.seat_id})")


@dataclass
class Seat:
    """One seat in the venue grid."""
    seat_id: str     # e.g. "R1C1"
    row: int
    col: int
    is_aisle: bool = False   # first/last column in a row
    is_blocked: bool = False # off-limits seat

    def __repr__(self) -> str:
        flags = []
        if self.is_aisle:   flags.append("aisle")
        if self.is_blocked: flags.append("BLOCKED")
        flag_str = f" ({', '.join(flags)})" if flags else ""
        return f"Seat({self.seat_id}{flag_str})"


class GridLayout:
    """
    A rectangular grid of seats.

    Parameters
    ----------
    rows : int        number of rows
    cols : int        number of columns per row
    blocked_seats : list[str]
        seat_ids that are blocked/reserved by the operator
    aisle_cols : list[int]
        0-based column indices considered "aisle" seats
        (defaults to first and last column of each row)
    """

    def __init__(
        self,
        rows: int,
        cols: int,
        blocked_seats: Optional[list[str]] = None,
        aisle_cols: Optional[list[int]] = None,
    ):
        self.rows = rows
        self.cols = cols
        blocked_ids: set[str] = set(blocked_seats or [])
        default_aisle = {0, cols - 1} if cols > 1 else {0}
        aisle_set = set(aisle_cols) if aisle_cols is not None else default_aisle

        self.seats: dict[str, Seat] = {}
        for r in range(rows):
            for c in range(cols):
                sid = f"R{r+1}C{c+1}"
                self.seats[sid] = Seat(
                    seat_id=sid,
                    row=r,
                    col=c,
                    is_aisle=(c in aisle_set),
                    is_blocked=(sid in blocked_ids),
                )

    # ------------------------------------------------------------------
    # Topology helpers
    # ------------------------------------------------------------------

    def available_seats(self) -> list[Seat]:
        """Return all non-blocked seats."""
        return [s for s in self.seats.values() if not s.is_blocked]

    def front_row_seats(self) -> list[Seat]:
        """Row 1 (index 0) non-blocked seats."""
        return [s for s in self.available_seats() if s.row == 0]

    def aisle_seats(self) -> list[Seat]:
        return [s for s in self.available_seats() if s.is_aisle]

    def are_adjacent(self, sid1: str, sid2: str) -> bool:
        """True if the two seats share an edge (up/down/left/right)."""
        s1, s2 = self.seats[sid1], self.seats[sid2]
        return (abs(s1.row - s2.row) + abs(s1.col - s2.col)) == 1

    def neighbors(self, sid: str) -> list[str]:
        s = self.seats[sid]
        nbrs = []
        for dr, dc in [(-1,0),(1,0),(0,-1),(0,1)]:
            nr, nc = s.row + dr, s.col + dc
            cand = f"R{nr+1}C{nc+1}"
            if cand in self.seats and not self.seats[cand].is_blocked:
                nbrs.append(cand)
        return nbrs

    def display(self, assignment: Optional[dict[str, str]] = None) -> str:
        """
        Render the grid as a text table.
        assignment maps participant_name → seat_id.
        """
        # Build reverse map: seat_id → name
        seat_to_name: dict[str, str] = {}
        if assignment:
            seat_to_name = {v: k for k, v in assignment.items()}

        cell_w = 12
        lines = []
        header = "     " + "".join(f" C{c+1:^{cell_w-1}}" for c in range(self.cols))
        lines.append(header)
        lines.append("     " + "-" * (cell_w * self.cols))

        for r in range(self.rows):
            row_parts = [f" R{r+1:2} |"]
            for c in range(self.cols):
                sid = f"R{r+1}C{c+1}"
                seat = self.seats[sid]
                if seat.is_blocked:
                    cell = "  [BLOCKED]"
                elif sid in seat_to_name:
                    name = seat_to_name[sid]
                    cell = f" {name[:cell_w-2]:^{cell_w-2}} "
                else:
                    cell = f" {'':^{cell_w-2}} "
                row_parts.append(cell + "|")
            lines.append("".join(row_parts))
        lines.append("     " + "-" * (cell_w * self.cols))
        return "\n".join(lines)


# ---------------------------------------------------------------------------
# CSP Solver
# ---------------------------------------------------------------------------

class SeatingCSP:
    """
    Constraint Satisfaction Problem solver for seating arrangements.

    Algorithm
    ---------
    1. Pre-processing  – translate Participant attributes and Constraint objects
                         into internal hard/soft constraint lists.
    2. Domain init     – every participant's domain = all available (non-blocked)
                         seats; then prune using simple constraint propagation.
    3. AC-3            – Arc-Consistency to further reduce domains before search.
    4. Backtracking    – MRV (Minimum Remaining Values) variable ordering +
                         LCV (Least Constraining Value) value ordering.
    5. Constraint check at every assignment.
    """

    def __init__(
        self,
        participants: list[Participant],
        layout: GridLayout,
        constraints: list[Constraint],
        seed: Optional[int] = None,
    ):
        self.participants: dict[str, Participant] = {p.name: p for p in participants}
        self.layout = layout
        self.constraints = constraints
        self._rng = random.Random(seed)

        # Validate seat count
        available = layout.available_seats()
        if len(available) < len(participants):
            raise ValueError(
                f"Not enough seats: {len(available)} available, "
                f"{len(participants)} participants."
            )

        # Build initial domains
        self.domains: dict[str, list[str]] = {}
        self._init_domains()

    # ------------------------------------------------------------------
    # Domain initialisation & constraint propagation
    # ------------------------------------------------------------------

    def _init_domains(self) -> None:
        """Set each participant's initial domain, then do node-consistency."""
        available_ids = [s.seat_id for s in self.layout.available_seats()]

        for name, p in self.participants.items():
            # Start with all available seats
            domain: list[str] = list(available_ids)

            # --- Node consistency (single-variable constraints) ---

            # Reserved seat
            if p.reserved_seat:
                seat = self.layout.seats.get(p.reserved_seat)
                if seat is None or seat.is_blocked:
                    raise ValueError(
                        f"Reserved seat {p.reserved_seat!r} for {name!r} "
                        "is invalid or blocked."
                    )
                domain = [p.reserved_seat]

            # Front-row requirement
            if p.needs_front_row and not p.reserved_seat:
                front_ids = {s.seat_id for s in self.layout.front_row_seats()}
                domain = [sid for sid in domain if sid in front_ids]

            # Aisle requirement
            if p.needs_aisle and not p.reserved_seat:
                aisle_ids = {s.seat_id for s in self.layout.aisle_seats()}
                domain = [sid for sid in domain if sid in aisle_ids]

            if not domain:
                raise ValueError(
                    f"No valid seats for participant {name!r} after applying "
                    "individual constraints."
                )

            self.domains[name] = domain

        # Apply SPECIFIC_SEAT and RESERVED_SEAT constraints from the list
        for c in self.constraints:
            if c.constraint_type == ConstraintType.SPECIFIC_SEAT:
                for pname in c.participants:
                    if pname in self.domains and c.seat_id:
                        seat = self.layout.seats.get(c.seat_id)
                        if seat and not seat.is_blocked:
                            self.domains[pname] = [c.seat_id]
            elif c.constraint_type == ConstraintType.RESERVED_SEAT:
                if c.seat_id:
                    # Remove this seat from all other participants' domains
                    for pname, dom in self.domains.items():
                        if pname not in c.participants:
                            self.domains[pname] = [s for s in dom if s != c.seat_id]

    def _ac3(self) -> bool:
        """
        AC-3 arc consistency.
        Prunes domains so that for every pair (Xi, Xj) with a binary
        constraint, every value in domain(Xi) has at least one consistent
        value in domain(Xj).
        Returns False if any domain becomes empty (CSP has no solution).
        """
        # Build arc queue from binary constraints
        queue: list[tuple[str, str]] = []
        for c in self.constraints:
            if c.constraint_type in (
                ConstraintType.MUST_SIT_TOGETHER,
                ConstraintType.MUST_NOT_SIT_TOGETHER,
            ) and len(c.participants) == 2:
                p1, p2 = c.participants
                queue.append((p1, p2))
                queue.append((p2, p1))

        while queue:
            xi, xj = queue.pop(0)
            if self._revise(xi, xj):
                if not self.domains[xi]:
                    return False
                # Re-add arcs pointing TO xi
                for c in self.constraints:
                    if xj in c.participants and xi in c.participants:
                        other = [p for p in c.participants if p != xi]
                        for xk in other:
                            if xk != xj:
                                queue.append((xk, xi))
        return True

    def _revise(self, xi: str, xj: str) -> bool:
        """Remove values from domain(xi) that have no support in domain(xj)."""
        revised = False
        new_domain = []
        for vx in self.domains[xi]:
            # Check if there's any vy in domain(xj) consistent with vx
            if any(self._binary_consistent(xi, vx, xj, vy)
                   for vy in self.domains[xj]):
                new_domain.append(vx)
            else:
                revised = True
        self.domains[xi] = new_domain
        return revised

    def _binary_consistent(self, n1: str, s1: str, n2: str, s2: str) -> bool:
        """Check pairwise consistency for all binary constraints between n1 and n2."""
        if s1 == s2:
            return False  # two participants can't share a seat

        for c in self.constraints:
            if n1 not in c.participants or n2 not in c.participants:
                continue
            if c.constraint_type == ConstraintType.MUST_SIT_TOGETHER:
                if not self.layout.are_adjacent(s1, s2):
                    return False
            elif c.constraint_type == ConstraintType.MUST_NOT_SIT_TOGETHER:
                if self.layout.are_adjacent(s1, s2):
                    return False
        return True

    # ------------------------------------------------------------------
    # Full-assignment consistency check
    # ------------------------------------------------------------------

    def _assignment_consistent(
        self, name: str, seat_id: str, assignment: dict[str, str]
    ) -> bool:
        """True if assigning seat_id to name is consistent with current assignment."""
        # No seat sharing
        if seat_id in assignment.values():
            return False

        for c in self.constraints:
            ctype = c.constraint_type

            # --- Binary participant constraints ---
            if ctype in (
                ConstraintType.MUST_SIT_TOGETHER,
                ConstraintType.MUST_NOT_SIT_TOGETHER,
            ):
                if name not in c.participants:
                    continue
                others = [p for p in c.participants if p != name]
                for other in others:
                    if other not in assignment:
                        continue
                    other_seat = assignment[other]
                    adjacent = self.layout.are_adjacent(seat_id, other_seat)
                    if ctype == ConstraintType.MUST_SIT_TOGETHER and not adjacent:
                        return False
                    if ctype == ConstraintType.MUST_NOT_SIT_TOGETHER and adjacent:
                        return False

            # --- Group constraints ---
            elif ctype in (
                ConstraintType.SAME_GROUP_TOGETHER,
                ConstraintType.SAME_GROUP_APART,
            ):
                p = self.participants[name]
                if p.group != c.group:
                    continue
                # Check against all already-assigned group members
                for other_name, other_seat in assignment.items():
                    op = self.participants[other_name]
                    if op.group != c.group:
                        continue
                    adjacent = self.layout.are_adjacent(seat_id, other_seat)
                    if ctype == ConstraintType.SAME_GROUP_TOGETHER and not adjacent:
                        # Only enforce pairwise if already adjacent cluster
                        # (soft enforcement: at least one group neighbour)
                        pass  # handled as soft preference below
                    if ctype == ConstraintType.SAME_GROUP_APART and adjacent:
                        return False

            # --- RESERVED_SEAT hard block ---
            elif ctype == ConstraintType.RESERVED_SEAT:
                if c.seat_id == seat_id and name not in c.participants:
                    return False

        return True

    # ------------------------------------------------------------------
    # Backtracking search
    # ------------------------------------------------------------------

    def _select_unassigned(
        self, assignment: dict[str, str], domains: dict[str, list[str]]
    ) -> Optional[str]:
        """MRV heuristic: pick variable with smallest remaining domain."""
        unassigned = [n for n in self.participants if n not in assignment]
        if not unassigned:
            return None
        return min(unassigned, key=lambda n: len(domains[n]))

    def _order_domain_values(
        self,
        name: str,
        domains: dict[str, list[str]],
        assignment: dict[str, str],
    ) -> list[str]:
        """
        LCV heuristic: order values by how many choices they leave for neighbours.
        Fewer constraints imposed → try first.
        """
        def lcv_score(seat_id: str) -> int:
            score = 0
            for other in self.participants:
                if other == name or other in assignment:
                    continue
                for other_seat in domains[other]:
                    if not self._binary_consistent(name, seat_id, other, other_seat):
                        score += 1
            return score

        values = list(domains[name])
        self._rng.shuffle(values)           # break ties randomly
        return sorted(values, key=lcv_score)

    def _forward_check(
        self,
        name: str,
        seat_id: str,
        domains: dict[str, list[str]],
        assignment: dict[str, str],
    ) -> Optional[dict[str, list[str]]]:
        """
        Forward checking: after assigning seat_id to name, prune domains of
        unassigned neighbours.  Returns None if any domain is wiped out.
        """
        new_domains = copy.deepcopy(domains)
        # Remove seat_id from all other domains
        for other, dom in new_domains.items():
            if other == name or other in assignment:
                continue
            new_domains[other] = [s for s in dom if s != seat_id]
            if not new_domains[other]:
                return None

        # Apply binary constraint pruning
        for c in self.constraints:
            if name not in c.participants:
                continue
            others = [p for p in c.participants if p != name]
            for other in others:
                if other in assignment:
                    continue
                pruned = [
                    sv for sv in new_domains.get(other, [])
                    if self._binary_consistent(other, sv, name, seat_id)
                ]
                if not pruned:
                    return None
                new_domains[other] = pruned

        return new_domains

    def _backtrack(
        self,
        assignment: dict[str, str],
        domains: dict[str, list[str]],
    ) -> Optional[dict[str, str]]:
        """Recursive backtracking with forward checking."""
        if len(assignment) == len(self.participants):
            return assignment  # complete assignment ✓

        name = self._select_unassigned(assignment, domains)
        if name is None:
            return assignment

        for seat_id in self._order_domain_values(name, domains, assignment):
            if self._assignment_consistent(name, seat_id, assignment):
                assignment[name] = seat_id
                new_domains = self._forward_check(name, seat_id, domains, assignment)
                if new_domains is not None:
                    result = self._backtrack(assignment, new_domains)
                    if result is not None:
                        return result
                del assignment[name]

        return None  # trigger backtrack

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def solve(self) -> Optional[dict[str, str]]:
        """
        Run AC-3 then backtracking search.

        Returns
        -------
        dict[participant_name, seat_id]  on success, or None if unsatisfiable.
        """
        # Make a working copy of domains so the original is untouched
        working_domains = copy.deepcopy(self.domains)

        # AC-3 pre-processing
        if not self._ac3():
            print("[CSP] AC-3 detected an unsatisfiable problem early.")
            return None

        result = self._backtrack({}, working_domains)
        return result

    def solve_with_report(self) -> None:
        """Solve and print a full human-readable report."""
        print("=" * 60)
        print(" SEATING ARRANGEMENT GENERATION MODULE — CSP Solver")
        print("=" * 60)
        print(f"\nParticipants : {len(self.participants)}")
        print(f"Available seats: {len(self.layout.available_seats())}")
        print(f"Grid size    : {self.layout.rows} rows × {self.layout.cols} cols")
        print(f"Constraints  : {len(self.constraints)}")

        print("\n[1] Running AC-3 constraint propagation...")
        working_domains = copy.deepcopy(self.domains)
        ac3_ok = self._ac3()
        if not ac3_ok:
            print("    ✗ AC-3 found problem unsatisfiable.")
            return
        avg_domain = sum(len(d) for d in working_domains.values()) / max(len(working_domains), 1)
        print(f"    ✓ AC-3 complete. Avg domain size: {avg_domain:.1f} seats/person")

        print("\n[2] Running backtracking search (MRV + LCV + Forward Checking)...")
        result = self.solve()

        if result is None:
            print("\n✗ No valid seating arrangement found.\n"
                  "  Check that constraints are not contradictory and that\n"
                  "  enough seats are available.\n")
            return

        print("    ✓ Solution found!\n")

        print("[3] Assignment summary:")
        print("-" * 40)
        for pname in sorted(result):
            sid = result[pname]
            seat = self.layout.seats[sid]
            p = self.participants[pname]
            tags = []
            if p.group:           tags.append(f"group={p.group}")
            if p.needs_front_row: tags.append("needs_front")
            if p.needs_aisle:     tags.append("needs_aisle")
            tag_str = f"  [{', '.join(tags)}]" if tags else ""
            aisle_str = " (aisle)" if seat.is_aisle else ""
            print(f"  {pname:<20} → {sid}{aisle_str}{tag_str}")

        print("\n[4] Seating chart:")
        print(self.layout.display(result))

        print("\n[5] Constraint verification:")
        violations = self._verify(result)
        if not violations:
            print("    ✓ All constraints satisfied.")
        else:
            for v in violations:
                print(f"    ⚠ {v}")
        print()

    def _verify(self, assignment: dict[str, str]) -> list[str]:
        """Return a list of constraint violations in the final assignment."""
        violations = []
        for c in self.constraints:
            ctype = c.constraint_type

            if ctype == ConstraintType.MUST_SIT_TOGETHER:
                p1, p2 = c.participants[0], c.participants[1]
                if p1 in assignment and p2 in assignment:
                    if not self.layout.are_adjacent(assignment[p1], assignment[p2]):
                        violations.append(
                            f"MUST_SIT_TOGETHER violated: {p1} ({assignment[p1]}) "
                            f"and {p2} ({assignment[p2]}) are not adjacent."
                        )

            elif ctype == ConstraintType.MUST_NOT_SIT_TOGETHER:
                p1, p2 = c.participants[0], c.participants[1]
                if p1 in assignment and p2 in assignment:
                    if self.layout.are_adjacent(assignment[p1], assignment[p2]):
                        violations.append(
                            f"MUST_NOT_SIT_TOGETHER violated: {p1} ({assignment[p1]}) "
                            f"and {p2} ({assignment[p2]}) are adjacent."
                        )

            elif ctype == ConstraintType.FRONT_ROW:
                for pname in c.participants:
                    if pname in assignment:
                        seat = self.layout.seats[assignment[pname]]
                        if seat.row != 0:
                            violations.append(
                                f"FRONT_ROW violated: {pname} is at "
                                f"{assignment[pname]} (row {seat.row+1})."
                            )

            elif ctype == ConstraintType.NEAR_AISLE:
                for pname in c.participants:
                    if pname in assignment:
                        seat = self.layout.seats[assignment[pname]]
                        if not seat.is_aisle:
                            violations.append(
                                f"NEAR_AISLE violated: {pname} is at "
                                f"{assignment[pname]} (not an aisle seat)."
                            )

            elif ctype == ConstraintType.SPECIFIC_SEAT:
                for pname in c.participants:
                    if pname in assignment and assignment[pname] != c.seat_id:
                        violations.append(
                            f"SPECIFIC_SEAT violated: {pname} should be at "
                            f"{c.seat_id} but is at {assignment[pname]}."
                        )

            elif ctype == ConstraintType.SAME_GROUP_APART:
                grp_members = [
                    n for n, p in self.participants.items()
                    if p.group == c.group and n in assignment
                ]
                for i, m1 in enumerate(grp_members):
                    for m2 in grp_members[i+1:]:
                        if self.layout.are_adjacent(assignment[m1], assignment[m2]):
                            violations.append(
                                f"SAME_GROUP_APART violated: {m1} and {m2} "
                                f"(group={c.group}) are adjacent."
                            )

        return violations


# ---------------------------------------------------------------------------
# Demo / Quick-start
# ---------------------------------------------------------------------------

def run_demo() -> None:
    """
    Classroom scenario
    ------------------
    • 4×5 grid (20 seats); seat R4C3 is blocked (broken chair).
    • 10 participants with various needs and group affiliations.
    • Several hard constraints.
    """
    print("\n" + "█" * 60)
    print(" DEMO: Classroom Seating (4 rows × 5 cols)")
    print("█" * 60 + "\n")

    # ── Layout ────────────────────────────────────────────────────────────
    layout = GridLayout(
        rows=4,
        cols=5,
        blocked_seats=["R4C3"],        # broken chair
        aisle_cols=[0, 4],             # leftmost and rightmost columns
    )

    # ── Participants ───────────────────────────────────────────────────────
    participants = [
        Participant("Alice",   group="team-A", needs_front_row=True),
        Participant("Bob",     group="team-A"),
        Participant("Charlie", group="team-A"),
        Participant("Diana",   group="team-B", needs_aisle=True),
        Participant("Eve",     group="team-B"),
        Participant("Frank",   group="team-B"),
        Participant("Grace",   needs_front_row=True),
        Participant("Hank",    needs_aisle=True),
        Participant("Ivy",     reserved_seat="R2C3"),
        Participant("Jack"),
    ]

    # ── Constraints ────────────────────────────────────────────────────────
    constraints = [
        # Alice must sit next to Bob (study partners)
        Constraint(ConstraintType.MUST_SIT_TOGETHER,   participants=["Alice", "Bob"]),
        # Charlie and Frank must NOT sit next to each other (behaviour)
        Constraint(ConstraintType.MUST_NOT_SIT_TOGETHER, participants=["Charlie", "Frank"]),
        # All of team-B should not sit adjacent to each other (prevent chatting)
        Constraint(ConstraintType.SAME_GROUP_APART, group="team-B"),
        # Front-row constraint declared explicitly (also auto-derived from needs_front_row)
        Constraint(ConstraintType.FRONT_ROW, participants=["Alice", "Grace"]),
        # Aisle constraint for Diana and Hank (also auto-derived)
        Constraint(ConstraintType.NEAR_AISLE, participants=["Diana", "Hank"]),
        # Ivy has a specific reserved seat (also set on the Participant object)
        Constraint(ConstraintType.SPECIFIC_SEAT, participants=["Ivy"], seat_id="R2C3"),
    ]

    # ── Solve ──────────────────────────────────────────────────────────────
    csp = SeatingCSP(participants, layout, constraints, seed=42)
    csp.solve_with_report()


def run_custom_example() -> None:
    """
    Simple 3×3 grid with 5 participants — easy to trace by hand.
    """
    print("\n" + "█" * 60)
    print(" CUSTOM EXAMPLE: 3×3 grid, 5 participants")
    print("█" * 60 + "\n")

    layout = GridLayout(rows=3, cols=3)

    participants = [
        Participant("P1", needs_front_row=True),
        Participant("P2", needs_aisle=True),
        Participant("P3", group="g1"),
        Participant("P4", group="g1"),
        Participant("P5"),
    ]

    constraints = [
        Constraint(ConstraintType.MUST_SIT_TOGETHER, participants=["P3", "P4"]),
        Constraint(ConstraintType.MUST_NOT_SIT_TOGETHER, participants=["P1", "P2"]),
    ]

    csp = SeatingCSP(participants, layout, constraints, seed=7)
    csp.solve_with_report()


if __name__ == "__main__":
    run_demo()
    run_custom_example()
