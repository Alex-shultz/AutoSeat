# SeatWise v0.3 — Smart Seating Planner

## Quick start
```bash
pip install flask
python app.py   # → http://127.0.0.1:5000
```

## What's new in v0.3
- **Seating Arrangement Module** — full CSP solver integration
- Add participants with name, group, front-row/aisle needs, reserved seat
- Add constraints: Must Sit Together, Must NOT Sit Together, Group Apart/Together,
  Front Row, Near Aisle, Specific Seat
- **Run CSP Solver** button — AC-3 + MRV + LCV + Forward Checking
- Live interactive grid shows colour-coded assignments by group
- Assignment table + violations panel in results
- JSON export for every arrangement

## Pages
| Route                       | Description                   |
|-----------------------------|-------------------------------|
| `/arrangements`             | Arrangements list             |
| `/arrangements/new`         | New arrangement editor        |
| `/arrangements/<id>`        | Edit / view existing          |

## Keyboard shortcuts (editor)
| Key        | Action        |
|------------|---------------|
| `Ctrl+S`   | Save          |
| `Ctrl+↵`   | Run solver    |
