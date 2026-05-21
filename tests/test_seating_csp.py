"""
test_seating_csp.py
===================
Unit tests for the seating_csp module (CSP solver core).

Tests cover:
- Data structures (Participant, Constraint, Seat, GridLayout)
- Domain initialization and filtering
- AC-3 constraint propagation
- Backtracking search with heuristics
- Constraint verification
"""

import pytest
from seating_csp import (
    Participant,
    Constraint,
    ConstraintType,
    Seat,
    GridLayout,
    SeatingCSP,
)


class TestParticipant:
    """Tests for the Participant dataclass."""

    def test_participant_basic(self):
        """Test basic participant creation."""
        p = Participant(name="Alice")
        assert p.name == "Alice"
        assert p.group is None
        assert p.needs_front_row is False
        assert p.needs_aisle is False
        assert p.reserved_seat is None

    def test_participant_with_group(self):
        """Test participant with group assignment."""
        p = Participant(name="Bob", group="Team A")
        assert p.name == "Bob"
        assert p.group == "Team A"

    def test_participant_with_needs(self):
        """Test participant with accessibility needs."""
        p = Participant(
            name="Carol",
            needs_front_row=True,
            needs_aisle=True,
        )
        assert p.needs_front_row is True
        assert p.needs_aisle is True

    def test_participant_reserved_seat(self):
        """Test participant with reserved seat."""
        p = Participant(name="Dave", reserved_seat="R1C1")
        assert p.reserved_seat == "R1C1"

    def test_participant_repr_basic(self):
        """Test string representation without tags."""
        p = Participant(name="Eve")
        assert "Eve" in repr(p)
        assert "group=" not in repr(p)

    def test_participant_repr_with_tags(self):
        """Test string representation with tags."""
        p = Participant(
            name="Frank",
            group="Dev",
            needs_front_row=True,
            needs_aisle=True,
            reserved_seat="R2C3",
        )
        r = repr(p)
        assert "Frank" in r
        assert "group=Dev" in r
        assert "front" in r
        assert "aisle" in r
        assert "seat=R2C3" in r


class TestConstraint:
    """Tests for the Constraint dataclass."""

    def test_constraint_must_sit_together(self):
        """Test MUST_SIT_TOGETHER constraint."""
        c = Constraint(
            constraint_type=ConstraintType.MUST_SIT_TOGETHER,
            participants=["Alice", "Bob"],
        )
        assert c.constraint_type == ConstraintType.MUST_SIT_TOGETHER
        assert c.participants == ["Alice", "Bob"]
        assert c.group is None
        assert c.seat_id is None

    def test_constraint_specific_seat(self):
        """Test SPECIFIC_SEAT constraint."""
        c = Constraint(
            constraint_type=ConstraintType.SPECIFIC_SEAT,
            participants=["Charlie"],
            seat_id="R1C1",
        )
        assert c.seat_id == "R1C1"

    def test_constraint_same_group(self):
        """Test SAME_GROUP_TOGETHER constraint."""
        c = Constraint(
            constraint_type=ConstraintType.SAME_GROUP_TOGETHER,
            group="Team X",
        )
        assert c.group == "Team X"


class TestSeat:
    """Tests for the Seat dataclass."""

    def test_seat_basic(self):
        """Test basic seat creation."""
        s = Seat(seat_id="R1C1", row=0, col=0)
        assert s.seat_id == "R1C1"
        assert s.row == 0
        assert s.col == 0
        assert s.is_aisle is False
        assert s.is_blocked is False

    def test_seat_aisle(self):
        """Test aisle seat."""
        s = Seat(seat_id="R1C1", row=0, col=0, is_aisle=True)
        assert s.is_aisle is True

    def test_seat_blocked(self):
        """Test blocked seat."""
        s = Seat(seat_id="R2C2", row=1, col=1, is_blocked=True)
        assert s.is_blocked is True

    def test_seat_repr_normal(self):
        """Test string representation of normal seat."""
        s = Seat(seat_id="R1C1", row=0, col=0)
        assert "R1C1" in repr(s)
        assert "aisle" not in repr(s)
        assert "BLOCKED" not in repr(s)

    def test_seat_repr_with_flags(self):
        """Test string representation with flags."""
        s = Seat(seat_id="R1C1", row=0, col=0, is_aisle=True, is_blocked=True)
        r = repr(s)
        assert "R1C1" in r
        assert "aisle" in r
        assert "BLOCKED" in r


class TestGridLayout:
    """Tests for the GridLayout class."""

    def test_grid_layout_creation_basic(self):
        """Test basic grid layout creation."""
        layout = GridLayout(rows=3, cols=4)
        assert layout.rows == 3
        assert layout.cols == 4
        assert len(layout.seats) == 12

    def test_grid_layout_seat_ids(self):
        """Test that seat IDs are correctly generated."""
        layout = GridLayout(rows=2, cols=2)
        assert "R1C1" in layout.seats
        assert "R1C2" in layout.seats
        assert "R2C1" in layout.seats
        assert "R2C2" in layout.seats

    def test_grid_layout_default_aisles(self):
        """Test default aisle columns (first and last)."""
        layout = GridLayout(rows=2, cols=4)
        # First column (col=0) and last column (col=3) should be aisles
        assert layout.seats["R1C1"].is_aisle is True
        assert layout.seats["R1C4"].is_aisle is True
        assert layout.seats["R1C2"].is_aisle is False
        assert layout.seats["R1C3"].is_aisle is False

    def test_grid_layout_custom_aisles(self):
        """Test custom aisle columns."""
        layout = GridLayout(rows=2, cols=4, aisle_cols=[1, 2])
        assert layout.seats["R1C1"].is_aisle is False
        assert layout.seats["R1C2"].is_aisle is True
        assert layout.seats["R1C3"].is_aisle is True
        assert layout.seats["R1C4"].is_aisle is False

    def test_grid_layout_blocked_seats(self):
        """Test blocked seats."""
        layout = GridLayout(rows=2, cols=2, blocked_seats=["R1C1"])
        assert layout.seats["R1C1"].is_blocked is True
        assert layout.seats["R1C2"].is_blocked is False

    def test_grid_layout_available_seats(self):
        """Test available seats method."""
        layout = GridLayout(rows=2, cols=2, blocked_seats=["R1C1"])
        available = layout.available_seats()
        assert len(available) == 3
        seat_ids = [s.seat_id for s in available]
        assert "R1C1" not in seat_ids

    def test_grid_layout_front_row_seats(self):
        """Test front row seats method."""
        layout = GridLayout(rows=3, cols=2)
        front = layout.front_row_seats()
        assert len(front) == 2
        for s in front:
            assert s.row == 0

    def test_grid_layout_aisle_seats(self):
        """Test aisle seats method."""
        layout = GridLayout(rows=2, cols=3)
        aisles = layout.aisle_seats()
        for s in aisles:
            assert s.is_aisle is True

    def test_grid_layout_are_adjacent_horizontal(self):
        """Test adjacency check - horizontal neighbors."""
        layout = GridLayout(rows=2, cols=3)
        assert layout.are_adjacent("R1C1", "R1C2") is True
        assert layout.are_adjacent("R1C2", "R1C3") is True

    def test_grid_layout_are_adjacent_vertical(self):
        """Test adjacency check - vertical neighbors."""
        layout = GridLayout(rows=3, cols=2)
        assert layout.are_adjacent("R1C1", "R2C1") is True
        assert layout.are_adjacent("R2C1", "R3C1") is True

    def test_grid_layout_are_not_adjacent_diagonal(self):
        """Test adjacency check - diagonal is not adjacent."""
        layout = GridLayout(rows=2, cols=2)
        assert layout.are_adjacent("R1C1", "R2C2") is False

    def test_grid_layout_are_not_adjacent_far(self):
        """Test adjacency check - far apart seats."""
        layout = GridLayout(rows=3, cols=3)
        assert layout.are_adjacent("R1C1", "R1C3") is False
        assert layout.are_adjacent("R1C1", "R3C1") is False

    def test_grid_layout_neighbors_center(self):
        """Test neighbors method for center seat."""
        layout = GridLayout(rows=3, cols=3)
        neighbors = layout.neighbors("R2C2")
        assert "R1C2" in neighbors  # up
        assert "R3C2" in neighbors  # down
        assert "R2C1" in neighbors  # left
        assert "R2C3" in neighbors  # right
        assert len(neighbors) == 4

    def test_grid_layout_neighbors_corner(self):
        """Test neighbors method for corner seat."""
        layout = GridLayout(rows=3, cols=3)
        neighbors = layout.neighbors("R1C1")
        assert "R1C2" in neighbors
        assert "R2C1" in neighbors
        assert len(neighbors) == 2

    def test_grid_layout_neighbors_blocked(self):
        """Test neighbors method excludes blocked seats."""
        layout = GridLayout(rows=2, cols=2, blocked_seats=["R1C2"])
        neighbors = layout.neighbors("R1C1")
        assert "R1C2" not in neighbors
        assert "R2C1" in neighbors

    def test_grid_layout_display(self):
        """Test layout display method."""
        layout = GridLayout(rows=2, cols=2)
        display = layout.display()
        # Display format uses "R 1", "R 2" etc with spaces
        assert "R 1" in display or "R1" in display
        assert "R 2" in display or "R2" in display
        assert "C" in display  # Column headers present


class TestSeatingCSP:
    """Tests for the SeatingCSP solver."""

    def _make_simple_layout(self):
        """Create a simple 2x2 layout for testing."""
        return GridLayout(rows=2, cols=2)

    def _make_simple_participants(self):
        """Create simple participants for testing."""
        return [
            Participant(name="Alice"),
            Participant(name="Bob"),
        ]

    def test_seating_csp_creation(self):
        """Test basic CSP creation."""
        layout = self._make_simple_layout()
        participants = self._make_simple_participants()
        csp = SeatingCSP(participants, layout, [])
        assert len(csp.participants) == 2
        assert "Alice" in csp.participants
        assert "Bob" in csp.participants

    def test_seating_csp_not_enough_seats(self):
        """Test error when not enough seats."""
        layout = GridLayout(rows=1, cols=1)  # Only 1 seat
        participants = [
            Participant(name="Alice"),
            Participant(name="Bob"),
        ]
        with pytest.raises(ValueError, match="Not enough seats"):
            SeatingCSP(participants, layout, [])

    def test_seating_csp_domain_initialization(self):
        """Test that domains are initialized correctly."""
        layout = self._make_simple_layout()
        participants = self._make_simple_participants()
        csp = SeatingCSP(participants, layout, [])
        
        assert "Alice" in csp.domains
        assert "Bob" in csp.domains
        assert len(csp.domains["Alice"]) == 4  # All 4 seats available
        assert len(csp.domains["Bob"]) == 4

    def test_seating_csp_solve_simple(self):
        """Test solving a simple arrangement."""
        layout = self._make_simple_layout()
        participants = self._make_simple_participants()
        csp = SeatingCSP(participants, layout, [])
        
        result = csp.solve()
        assert result is not None
        assert "Alice" in result
        assert "Bob" in result
        assert result["Alice"] != result["Bob"]  # Different seats

    def test_seating_csp_must_sit_together(self):
        """Test MUST_SIT_TOGETHER constraint."""
        layout = GridLayout(rows=1, cols=4)
        participants = [
            Participant(name="Alice"),
            Participant(name="Bob"),
        ]
        constraints = [
            Constraint(
                constraint_type=ConstraintType.MUST_SIT_TOGETHER,
                participants=["Alice", "Bob"],
            ),
        ]
        csp = SeatingCSP(participants, layout, constraints)
        result = csp.solve()
        
        assert result is not None
        assert layout.are_adjacent(result["Alice"], result["Bob"])

    def test_seating_csp_must_not_sit_together(self):
        """Test MUST_NOT_SIT_TOGETHER constraint."""
        layout = GridLayout(rows=1, cols=4)
        participants = [
            Participant(name="Alice"),
            Participant(name="Bob"),
        ]
        constraints = [
            Constraint(
                constraint_type=ConstraintType.MUST_NOT_SIT_TOGETHER,
                participants=["Alice", "Bob"],
            ),
        ]
        csp = SeatingCSP(participants, layout, constraints)
        result = csp.solve()
        
        assert result is not None
        assert not layout.are_adjacent(result["Alice"], result["Bob"])

    def test_seating_csp_front_row_need(self):
        """Test participant needing front row."""
        layout = GridLayout(rows=3, cols=2)
        participants = [
            Participant(name="Alice", needs_front_row=True),
            Participant(name="Bob"),
        ]
        csp = SeatingCSP(participants, layout, [])
        result = csp.solve()
        
        assert result is not None
        alice_seat = layout.seats[result["Alice"]]
        assert alice_seat.row == 0  # Front row

    def test_seating_csp_aisle_need(self):
        """Test participant needing aisle seat."""
        layout = GridLayout(rows=2, cols=4)
        participants = [
            Participant(name="Alice", needs_aisle=True),
            Participant(name="Bob"),
        ]
        csp = SeatingCSP(participants, layout, [])
        result = csp.solve()
        
        assert result is not None
        alice_seat = layout.seats[result["Alice"]]
        assert alice_seat.is_aisle is True

    def test_seating_csp_reserved_seat(self):
        """Test participant with reserved seat."""
        layout = self._make_simple_layout()
        participants = [
            Participant(name="Alice", reserved_seat="R1C1"),
            Participant(name="Bob"),
        ]
        csp = SeatingCSP(participants, layout, [])
        result = csp.solve()
        
        assert result is not None
        assert result["Alice"] == "R1C1"

    def test_seating_csp_specific_seat_constraint(self):
        """Test SPECIFIC_SEAT constraint."""
        layout = self._make_simple_layout()
        participants = [
            Participant(name="Alice"),
            Participant(name="Bob"),
        ]
        constraints = [
            Constraint(
                constraint_type=ConstraintType.SPECIFIC_SEAT,
                participants=["Alice"],
                seat_id="R2C2",
            ),
        ]
        csp = SeatingCSP(participants, layout, constraints)
        result = csp.solve()
        
        assert result is not None
        assert result["Alice"] == "R2C2"

    def test_seating_csp_unsolvable(self):
        """Test detecting unsolvable constraints."""
        layout = GridLayout(rows=1, cols=2)
        participants = [
            Participant(name="Alice"),
            Participant(name="Bob"),
            Participant(name="Carol"),
        ]
        # This raises ValueError during initialization due to not enough seats
        with pytest.raises(ValueError, match="Not enough seats"):
            SeatingCSP(participants, layout, [])

    def test_seating_csp_contradictory_constraints(self):
        """Test detecting contradictory constraints."""
        layout = GridLayout(rows=1, cols=4)
        participants = [
            Participant(name="Alice"),
            Participant(name="Bob"),
        ]
        # Contradictory: must sit together AND must not sit together
        constraints = [
            Constraint(
                constraint_type=ConstraintType.MUST_SIT_TOGETHER,
                participants=["Alice", "Bob"],
            ),
            Constraint(
                constraint_type=ConstraintType.MUST_NOT_SIT_TOGETHER,
                participants=["Alice", "Bob"],
            ),
        ]
        csp = SeatingCSP(participants, layout, constraints)
        result = csp.solve()
        
        assert result is None  # Contradictory constraints

    def test_seating_csp_verify_no_violations(self):
        """Test constraint verification with valid assignment."""
        layout = self._make_simple_layout()
        participants = self._make_simple_participants()
        csp = SeatingCSP(participants, layout, [])
        result = csp.solve()
        
        violations = csp._verify(result)
        assert len(violations) == 0

    def test_seating_csp_same_group_together(self):
        """Test SAME_GROUP_TOGETHER constraint."""
        layout = GridLayout(rows=1, cols=4)
        participants = [
            Participant(name="Alice", group="Team A"),
            Participant(name="Bob", group="Team A"),
            Participant(name="Carol", group="Team B"),
        ]
        constraints = [
            Constraint(
                constraint_type=ConstraintType.SAME_GROUP_TOGETHER,
                group="Team A",
            ),
        ]
        csp = SeatingCSP(participants, layout, constraints)
        result = csp.solve()
        
        assert result is not None
        # Alice and Bob should be adjacent
        assert layout.are_adjacent(result["Alice"], result["Bob"])

    def test_seating_csp_deterministic_with_seed(self):
        """Test that seeding produces deterministic results."""
        layout = self._make_simple_layout()
        participants = self._make_simple_participants()
        
        csp1 = SeatingCSP(participants, layout, [], seed=42)
        csp2 = SeatingCSP(participants, layout, [], seed=42)
        
        result1 = csp1.solve()
        result2 = csp2.solve()
        
        assert result1 == result2  # Same seed = same result


class TestSeatingCSPVerify:
    """Tests for the _verify method specifically."""

    def test_verify_front_row_violation(self):
        """Test detecting FRONT_ROW violation."""
        layout = GridLayout(rows=2, cols=2)
        participants = [Participant(name="Alice")]
        constraints = [
            Constraint(
                constraint_type=ConstraintType.FRONT_ROW,
                participants=["Alice"],
            ),
        ]
        csp = SeatingCSP(participants, layout, constraints, seed=42)
        # Manually create a violating assignment
        assignment = {"Alice": "R2C1"}  # Not front row
        
        violations = csp._verify(assignment)
        assert len(violations) > 0
        assert "FRONT_ROW" in violations[0]

    def test_verify_near_aisle_violation(self):
        """Test detecting NEAR_AISLE violation."""
        layout = GridLayout(rows=2, cols=3)
        participants = [Participant(name="Alice")]
        constraints = [
            Constraint(
                constraint_type=ConstraintType.NEAR_AISLE,
                participants=["Alice"],
            ),
        ]
        csp = SeatingCSP(participants, layout, constraints, seed=42)
        # Manually create a violating assignment (middle seat)
        assignment = {"Alice": "R1C2"}  # Middle seat, not aisle
        
        violations = csp._verify(assignment)
        assert len(violations) > 0
        assert "NEAR_AISLE" in violations[0]

    def test_verify_must_sit_together_violation(self):
        """Test detecting MUST_SIT_TOGETHER violation."""
        layout = GridLayout(rows=2, cols=2)
        participants = [
            Participant(name="Alice"),
            Participant(name="Bob"),
        ]
        constraints = [
            Constraint(
                constraint_type=ConstraintType.MUST_SIT_TOGETHER,
                participants=["Alice", "Bob"],
            ),
        ]
        csp = SeatingCSP(participants, layout, constraints, seed=42)
        # Manually create a violating assignment (diagonal)
        assignment = {"Alice": "R1C1", "Bob": "R2C2"}
        
        violations = csp._verify(assignment)
        assert len(violations) > 0
        assert "MUST_SIT_TOGETHER" in violations[0]

    def test_verify_must_not_sit_together_violation(self):
        """Test detecting MUST_NOT_SIT_TOGETHER violation."""
        layout = GridLayout(rows=1, cols=3)
        participants = [
            Participant(name="Alice"),
            Participant(name="Bob"),
        ]
        constraints = [
            Constraint(
                constraint_type=ConstraintType.MUST_NOT_SIT_TOGETHER,
                participants=["Alice", "Bob"],
            ),
        ]
        csp = SeatingCSP(participants, layout, constraints, seed=42)
        # Manually create a violating assignment (adjacent)
        assignment = {"Alice": "R1C1", "Bob": "R1C2"}
        
        violations = csp._verify(assignment)
        assert len(violations) > 0
        assert "MUST_NOT_SIT_TOGETHER" in violations[0]

    def test_verify_same_group_apart_violation(self):
        """Test detecting SAME_GROUP_APART violation."""
        layout = GridLayout(rows=1, cols=3)
        participants = [
            Participant(name="Alice", group="Team A"),
            Participant(name="Bob", group="Team A"),
        ]
        constraints = [
            Constraint(
                constraint_type=ConstraintType.SAME_GROUP_APART,
                group="Team A",
            ),
        ]
        csp = SeatingCSP(participants, layout, constraints, seed=42)
        # Manually create a violating assignment (adjacent)
        assignment = {"Alice": "R1C1", "Bob": "R1C2"}
        
        violations = csp._verify(assignment)
        assert len(violations) > 0
        assert "SAME_GROUP_APART" in violations[0]
