# TDR blockchain scheduler

How to run it and what each screen check should show: [TESTING.md](TESTING.md).

How the stages move: [FLOW.md](FLOW.md).

URL, body, internal calls, checks, and output for each scheduler API: [API-CONTRACT.md](API-CONTRACT.md).

Which TDR and MPSDC API belongs to which use case: [API-USE-CASES.md](API-USE-CASES.md).

- `scheduler/` — service. Start with `python3 -m schedulermp serve`.
- `frontend/` — admin screen, served by the scheduler at `/`.
- `scheduler/postman/TDR-Scheduler.postman_collection.json` — Login, then health, status, and the three phase runs.
