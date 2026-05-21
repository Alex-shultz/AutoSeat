"""
test_csp_bridge.py
==================
Unit tests for the csp_bridge module (adapter layer).

Tests cover:
- Building CSP layout from venue data
- Building CSP participants from JSON data
- Building CSP constraints from JSON data
- Running the CSP solver end-to-end
"""

import pytest
from csp_bridge import (
    build_csp_layout,
    build_csp_participants,
    build_csp_constraints,
    run_csp,
)


class MockVenueRow:
    """Mock venue row for testing."""
    
    def __init__(self, rows, cols, layout_json):
        self["rows"] = rows
        self["cols"] = cols
        self["layout_json"] = layout_json
    
    def __getitem__(self, key):
        return getattr(self, key, None)
    
    def __setitem__(self, key, value):
        setattr(self, key, value)


def _make_venue_layout_json(rows, cols, blocked=None, aisles=None):
    """Helper to create venue layout JSON."""
    seats = {}
    aisle_cols = aisles if aisles else {0, cols - 1}
    
    for r in range(rows):
        for c in range(cols):
            sid = f"R{r+1}C{c+1}"
            is_aisle = c in aisle_cols
            is_front = r == 0
            is_blocked = blocked and sid in blocked
            
            seat_type = "normal"
            if is_blocked:
                seat_type = "blocked"
            elif is_front:
                seat_type = "front"
            elif is_aisle:
                seat_type = "aisle"
            
            seats[sid] = {
                "id": sid,
                "row": r,
                "col": c,
                "type": seat_type,
                "label": "",
                "is_blocked": is_blocked,
                "is_aisle": is_aisle,
                "is_front": is_front,
            }
    
    import json
    return json.dumps({
        "schema_version": "1.0",
        "rows": rows,
        "cols": cols,
        "seats": seats,
    })


class TestBuildCSPLayout:
    """Tests for build_csp_layout function."""
    
    def test_build_layout_basic(self):
        """Test basic layout building."""
        layout_json = _make_venue_layout_json(2, 2)
        venue = MockVenueRow(2, 2, layout_json)
        
        layout = build_csp_layout(venue)
        
        assert layout.rows == 2
        assert layout.cols == 2
        assert len(layout.seats) == 4
    
    def test_build_layout_with_blocked_seats(self):
        """Test layout with blocked seats."""
        layout_json = _make_venue_layout_json(2, 2, blocked=["R1C1"])
        venue = MockVenueRow(2, 2, layout_json)
        
        layout = build_csp_layout(venue)
        
        assert layout.seats["R1C1"].is_blocked is True
        assert layout.seats["R1C2"].is_blocked is False
        
        available = layout.available_seats()
        assert len(available) == 3
    
    def test_build_layout_detects_aisles(self):
        """Test that aisle columns are detected correctly."""
        layout_json = _make_venue_layout_json(2, 4)
        venue = MockVenueRow(2, 4, layout_json)
        
        layout = build_csp_layout(venue)
        
        # First and last columns should be aisles
        assert layout.seats["R1C1"].is_aisle is True
        assert layout.seats["R1C4"].is_aisle is True
        assert layout.seats["R1C2"].is_aisle is False


class TestBuildCSPParticipants:
    """Tests for build_csp_participants function."""
    
    def test_build_participants_basic(self):
        """Test basic participant building."""
        data = [
            {"name": "Alice"},
            {"name": "Bob"},
        ]
        
        participants = build_csp_participants(data)
        
        assert len(participants) == 2
        assert participants[0].name == "Alice"
        assert participants[1].name == "Bob"
    
    def test_build_participants_with_group(self):
        """Test participants with group assignments."""
        data = [
            {"name": "Alice", "group": "Team A"},
            {"name": "Bob", "group": "Team B"},
        ]
        
        participants = build_csp_participants(data)
        
        assert participants[0].group == "Team A"
        assert participants[1].group == "Team B"
    
    def test_build_participants_with_needs(self):
        """Test participants with accessibility needs."""
        data = [
            {"name": "Alice", "needs_front_row": 1},
            {"name": "Bob", "needs_aisle": 1},
        ]
        
        participants = build_csp_participants(data)
        
        assert participants[0].needs_front_row is True
        assert participants[1].needs_aisle is True
    
    def test_build_participants_with_reserved_seat(self):
        """Test participants with reserved seats."""
        data = [
            {"name": "Alice", "reserved_seat": "R1C1"},
        ]
        
        participants = build_csp_participants(data)
        
        assert participants[0].reserved_seat == "R1C1"
    
    def test_build_participants_empty_list(self):
        """Test empty participant list."""
        data = []
        
        participants = build_csp_participants(data)
        
        assert len(participants) == 0


class TestBuildCSPConstraints:
    """Tests for build_csp_constraints function."""
    
    def test_build_constraints_must_sit_together(self):
        """Test MUST_SIT_TOGETHER constraint."""
        from seating_csp import ConstraintType
        
        data = [
            {"type": "MUST_SIT_TOGETHER", "participants": ["Alice", "Bob"]},
        ]
        
        constraints = build_csp_constraints(data)
        
        assert len(constraints) == 1
        assert constraints[0].constraint_type == ConstraintType.MUST_SIT_TOGETHER
        assert constraints[0].participants == ["Alice", "Bob"]
    
    def test_build_constraints_must_not_sit_together(self):
        """Test MUST_NOT_SIT_TOGETHER constraint."""
        from seating_csp import ConstraintType
        
        data = [
            {"type": "MUST_NOT_SIT_TOGETHER", "participants": ["Alice", "Bob"]},
        ]
        
        constraints = build_csp_constraints(data)
        
        assert len(constraints) == 1
        assert constraints[0].constraint_type == ConstraintType.MUST_NOT_SIT_TOGETHER
    
    def test_build_constraints_front_row(self):
        """Test FRONT_ROW constraint."""
        from seating_csp import ConstraintType
        
        data = [
            {"type": "FRONT_ROW", "participants": ["Alice"]},
        ]
        
        constraints = build_csp_constraints(data)
        
        assert len(constraints) == 1
        assert constraints[0].constraint_type == ConstraintType.FRONT_ROW
    
    def test_build_constraints_near_aisle(self):
        """Test NEAR_AISLE constraint."""
        from seating_csp import ConstraintType
        
        data = [
            {"type": "NEAR_AISLE", "participants": ["Bob"]},
        ]
        
        constraints = build_csp_constraints(data)
        
        assert len(constraints) == 1
        assert constraints[0].constraint_type == ConstraintType.NEAR_AISLE
    
    def test_build_constraints_specific_seat(self):
        """Test SPECIFIC_SEAT constraint."""
        from seating_csp import ConstraintType
        
        data = [
            {"type": "SPECIFIC_SEAT", "participants": ["Alice"], "seat_id": "R1C1"},
        ]
        
        constraints = build_csp_constraints(data)
        
        assert len(constraints) == 1
        assert constraints[0].constraint_type == ConstraintType.SPECIFIC_SEAT
        assert constraints[0].seat_id == "R1C1"
    
    def test_build_constraints_same_group(self):
        """Test SAME_GROUP_TOGETHER constraint."""
        from seating_csp import ConstraintType
        
        data = [
            {"type": "SAME_GROUP_TOGETHER", "group": "Team A"},
        ]
        
        constraints = build_csp_constraints(data)
        
        assert len(constraints) == 1
        assert constraints[0].constraint_type == ConstraintType.SAME_GROUP_TOGETHER
        assert constraints[0].group == "Team A"
    
    def test_build_constraints_invalid_type_skipped(self):
        """Test that invalid constraint types are skipped."""
        data = [
            {"type": "INVALID_TYPE", "participants": ["Alice"]},
            {"type": "MUST_SIT_TOGETHER", "participants": ["Bob", "Carol"]},
        ]
        
        constraints = build_csp_constraints(data)
        
        assert len(constraints) == 1  # Only valid one included
    
    def test_build_constraints_empty_list(self):
        """Test empty constraint list."""
        data = []
        
        constraints = build_csp_constraints(data)
        
        assert len(constraints) == 0


class TestRunCSP:
    """Tests for run_csp function."""
    
    def test_run_csp_simple_success(self):
        """Test successful simple arrangement."""
        layout_json = _make_venue_layout_json(2, 2)
        venue = MockVenueRow(2, 2, layout_json)
        
        participants = [{"name": "Alice"}, {"name": "Bob"}]
        constraints = []
        
        result, error = run_csp(venue, participants, constraints)
        
        assert result is not None
        assert error is None
        assert "assignment" in result
        assert "Alice" in result["assignment"]
        assert "Bob" in result["assignment"]
    
    def test_run_csp_with_constraint(self):
        """Test arrangement with constraint."""
        layout_json = _make_venue_layout_json(1, 4)
        venue = MockVenueRow(1, 4, layout_json)
        
        participants = [{"name": "Alice"}, {"name": "Bob"}]
        constraints = [
            {"type": "MUST_SIT_TOGETHER", "participants": ["Alice", "Bob"]},
        ]
        
        result, error = run_csp(venue, participants, constraints)
        
        assert result is not None
        assert error is None
        # Verify they are adjacent
        from seating_csp import GridLayout
        temp_layout = GridLayout(1, 4)
        assert temp_layout.are_adjacent(
            result["assignment"]["Alice"],
            result["assignment"]["Bob"]
        )
    
    def test_run_csp_no_solution(self):
        """Test when no solution exists."""
        layout_json = _make_venue_layout_json(1, 1)
        venue = MockVenueRow(1, 1, layout_json)
        
        participants = [{"name": "Alice"}, {"name": "Bob"}]
        constraints = []
        
        result, error = run_csp(venue, participants, constraints)
        
        assert result is None
        assert error is not None
        assert "Not enough seats" in error or "No valid arrangement" in error
    
    def test_run_csp_contradictory_constraints(self):
        """Test contradictory constraints."""
        layout_json = _make_venue_layout_json(1, 4)
        venue = MockVenueRow(1, 4, layout_json)
        
        participants = [{"name": "Alice"}, {"name": "Bob"}]
        constraints = [
            {"type": "MUST_SIT_TOGETHER", "participants": ["Alice", "Bob"]},
            {"type": "MUST_NOT_SIT_TOGETHER", "participants": ["Alice", "Bob"]},
        ]
        
        result, error = run_csp(venue, participants, constraints)
        
        assert result is None
        assert error is not None
    
    def test_run_csp_returns_stats(self):
        """Test that result includes statistics."""
        layout_json = _make_venue_layout_json(2, 2)
        venue = MockVenueRow(2, 2, layout_json)
        
        participants = [{"name": "Alice"}, {"name": "Bob"}]
        constraints = []
        
        result, error = run_csp(venue, participants, constraints)
        
        assert result is not None
        assert "stats" in result
        assert "participants" in result["stats"]
        assert "seats_used" in result["stats"]
        assert "violations" in result["stats"]
    
    def test_run_csp_returns_timestamp(self):
        """Test that result includes timestamp."""
        layout_json = _make_venue_layout_json(2, 2)
        venue = MockVenueRow(2, 2, layout_json)
        
        participants = [{"name": "Alice"}]
        constraints = []
        
        result, error = run_csp(venue, participants, constraints)
        
        assert result is not None
        assert "solved_at" in result
    
    def test_run_csp_no_violations_on_valid(self):
        """Test that valid solutions have no violations."""
        layout_json = _make_venue_layout_json(2, 2)
        venue = MockVenueRow(2, 2, layout_json)
        
        participants = [{"name": "Alice"}, {"name": "Bob"}]
        constraints = []
        
        result, error = run_csp(venue, participants, constraints)
        
        assert result is not None
        assert result["violations"] == []
