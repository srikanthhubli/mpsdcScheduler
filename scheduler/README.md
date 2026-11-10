# Scheduler

Reads TDR DataSharing and writes the four MP-TDR blockchain APIs.

| Stage | Write | Read-back |
|---|---|---|
| Generating area | `POST /Agency/InsertGeneratingArea` | `GET /Agency/GetApplicationDetails` |
| Owner | `POST /Agency/InsertOwnerDetail` | `GET /api/tdr/owners/{ownerId}` |
| DRC | `POST /Department/DRCUpload` | `GET /Agency/GetDRCDetails` |
| Transfer | `POST /User/InsertTransferRequest` | no separate read-back |

Owner and DRC reads use the v1.4 envelope (`success`, `statusCode`, `message`, `data`). If that route is missing, the scheduler falls back to `GetOwnerDetails` and `GetDRCDetails`. Certificate numbers keep their slashes in the DRC path.

`InsertOwnerDetail` requires `applicationid`, `owner_id`, and `ownernm`. A transfer whose `trn_value_tdr` is above `remaining_value_tdr` is failed before the write, matching the Fabric validation.

Phase 1 only compares DRCs. It does not write. Phase 2 migrates the application list. Phase 3 syncs one live application, or polls ids that are not already `SUCCESS`.

```bash
cp .env.example .env
python3 -m schedulermp serve
python3 -m schedulermp phase1 --certificate "DRC/2024/00002/Indore"
python3 -m schedulermp phase2 --application-id TDR202471184557197
python3 -m schedulermp phase3 --application-id TDR202471184557197 --certificate "DRC/2024/00002/Indore"
python3 -m unittest tests.test_sync
```

`DRY_RUN=true` builds bodies and does not POST them. The admin screen is served at `http://127.0.0.1:8088/`. Sign in as `admin`. The full run and test steps are in `../TESTING.md`.

Postman: `postman/TDR-Scheduler.postman_collection.json`.

Set `BLOCKCHAIN_API_KEY` to the MP-TDR `X-API-Key`. The UAT host needs legacy TLS renegotiation; the scheduler turns that on. Without a real key, phase 1 still reads TDR and records the blockchain 401 as `API_FAILURE`.
