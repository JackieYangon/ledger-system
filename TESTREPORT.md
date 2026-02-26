# Test Report

## Summary
- Status: FAILED (environment missing Python packages)
- Date: 2026-02-26

## Test Command
```bash
python3 -m pytest -q
```

## Result (Output Summary)
- Error: `/usr/bin/python3: No module named pytest`
- Follow-up attempts to install dependencies failed because `pip` is not available in this environment.

## Coverage Notes
The pytest suite in `tests/test_app.py` covers all acceptance criteria by validating:
- Role-based access and visibility between admin/user/readonly users.
- Transaction creation with required fields and list visibility.
- Filtering by date range, category, account, amount range, and keyword.
- Monthly/yearly report totals and category breakdown presence.
- Budget creation and spent tracking.
- CSV export results.
- Core desktop flow pages render and contain primary actions.

## How To Run Locally
1. Ensure Python dependencies are installed:
   - `pip install -r requirements.txt`
2. Run tests:
   - `python -m pytest -q`
