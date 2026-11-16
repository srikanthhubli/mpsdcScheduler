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

Run these from this directory. The same process serves the API and the admin screen in `../frontend/`.

```bash
cp .env.example .env
```

Set `BLOCKCHAIN_API_KEY`. Change `ADMIN_PASSWORD` on the server. Leave `HTTP_HOST=0.0.0.0` and `HTTP_PORT=8088` so a browser can open the screen.

```bash
python3 -m schedulermp serve
```

That stays in the terminal. For a background process that restarts if it exits:

```bash
chmod +x tdrctl
./tdrctl start
./tdrctl status
./tdrctl logs -f
./tdrctl restart
./tdrctl stop
```

As root, `python3 -m schedulermp install` registers systemd service `tdr-scheduler` and starts it on boot. After that, `./tdrctl` controls the service.

Open `http://<server>:8088/` and sign in with `ADMIN_USERNAME` and `ADMIN_PASSWORD`. The sample values are `admin` and `admin`. Do not open `frontend/index.html` as a file.

One-off runs, without the screen:

```bash
python3 -m schedulermp phase1 --certificate "DRC/2024/00002/Indore"
python3 -m schedulermp phase2 --application-id TDR202471184557197
python3 -m schedulermp phase3 --application-id TDR202471184557197 --certificate "DRC/2024/00002/Indore"
python3 -m unittest tests.test_sync
```

`DRY_RUN=true` builds bodies and does not POST them. The full screen checks are in `../TESTING.md`.

Postman: `postman/TDR-Scheduler.postman_collection.json`.

Set `BLOCKCHAIN_API_KEY` to the MP-TDR `X-API-Key`. The UAT host needs legacy TLS renegotiation; the scheduler turns that on. Without a real key, phase 1 still reads TDR and records the blockchain 401 as `API_FAILURE`.
