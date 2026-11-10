# Scheduler API contract

Base URL: `http://<server>:8088`

Every path except `POST /login` and the screen files needs a header:

```http
Authorization: Bearer <token>
```

The token comes from `POST /login`. A missing or wrong token returns:

```json
{ "status": "FAILED", "message": "Login required" }
```

HTTP status `401`.

TDR base used inside the scheduler: `TDR_BASE_URL`, normally `https://gisdemo.mp.gov.in/TDR/TDRService/api/DataSharing`.

MPSDC base: `BLOCKCHAIN_BASE_URL`, normally `https://mpbsp-uat.mp.gov.in`. Business calls also send `X-API-Key` and `channel`, `org`, `peer`.

## Errors the scheduler returns

| HTTP | When | Body |
|---|---|---|
| 400 | Body is not a JSON object, `limit` is not a whole number, `ownerIds` is not a list, or the schedule hours are outside 1–12 | `{ "status": "FAILED", "message": "<what to correct>" }` |
| 401 | Login failed or the token is missing | `{ "status": "FAILED", "message": "Invalid username or password" }` or `Login required` |
| 404 | Unknown path, or that certificate or job is not stored | `{ "status": "NOT_FOUND", "message": "<which record>" }` |
| 409 | Phase 2 or phase 3 is already running, or pause/stop was asked when nothing is running | `{ "status": "FAILED", "message": "Phase 2 is already running" }` |
| 502 | TDR or MPSDC could not be called before the run stored a row. `retryable` is true for timeouts, connection failures, and HTTP 429/500/502/503/504 | `{ "status": "FAILED", "message": "TDR HTTP 503: ...", "retryable": true }` |
| 500 | The scheduler itself failed. The message is the error text. The stack stays in the server log | `{ "status": "FAILED", "message": "<error>" }` |

A certificate that TDR or MPSDC rejects during phase 1 is not a 502. The HTTP response is 200 and that row's `status` is `API_FAILURE`, `NOT_FOUND`, or `MISMATCH`. The same rule applies to one stage inside a phase 2 or phase 3 job: the HTTP call to the scheduler succeeds, and the job `status` is `FAILED` with `last_error` set.

Connection failures are worded `TDR connection failed: ...` or `Blockchain connection failed: ...`. A non-JSON body from either system is `returned a body that is not JSON`.

## POST /login

No token.

```http
POST /login
Content-Type: application/json

{ "username": "admin", "password": "admin" }
```

Success `200`:

```json
{ "status": "SUCCESS", "username": "admin", "token": "<session token>" }
```

Wrong password `401`: `{ "status": "FAILED", "message": "Invalid username or password" }`.

No internal TDR or MPSDC call.

## POST /logout

```http
POST /logout
Authorization: Bearer <token>
```

Success `200`: `{ "status": "SUCCESS", "message": "Signed out" }`.

## GET /health

Success `200`: `{ "status": "ok" }`.

This only means the scheduler process is up. It does not call TDR or MPSDC.

## GET /status

Success `200`:

```json
{
  "phase1_enabled": false,
  "phase2_enabled": false,
  "phase3_enabled": false,
  "dry_run": false,
  "verifications": { "MATCH": 1 },
  "jobs": { "SUCCESS": 1 },
  "schedule": { "schedule": { "legacy": { "enabled": false, "start": "01:00", "hours": 4 } } }
}
```

`phase2_enabled` is the legacy daily schedule. `verifications` and `jobs` are counts already stored on this server. No live TDR or MPSDC call.

## POST /run/phase1

Checks certificates. Does not write the ledger.

```http
POST /run/phase1
Content-Type: application/json

{ "certificate": "DRC/2024/00002/Indore", "limit": 1 }
```

Leave `certificate` empty to walk `GetDRCNoList`. `limit` 0 means no cap. `limit` must be 0 or greater.

Success `200`:

```json
{
  "summary": { "total": 1, "MATCH": 1, "MISMATCH": 0, "NOT_FOUND": 0, "API_FAILURE": 0 },
  "results": [
    {
      "certificate_no": "DRC/2024/00002/Indore",
      "application_id": "TDR202471184557197",
      "status": "MATCH",
      "message": "DRC fields match",
      "on_chain": true,
      "flg": "FIRST_OWNER",
      "chain_action": "generate",
      "diffs": [],
      "checked_at": "2026-11-10T08:00:00+00:00"
    }
  ]
}
```

Internal calls, in order:

| Step | Call | Check |
|---|---|---|
| 1, only when the certificate is blank | `GET {TDR}/GetDRCNoList` | Uses `certificate_numbers` from the body |
| 2 | `GET {TDR}/GetDetailByCertificateNo?certificateNo=` | Status `failed` or no matching certificate becomes `NOT_FOUND`. A transport or HTTP error becomes `API_FAILURE` |
| 3 | `GET {MPSDC}/Agency/GetDRCDetails?certificateNumber=` | Missing record is `MISMATCH` with message `MISSING_ON_BLOCKCHAIN` and `on_chain` false |
| 4, only if step 3 is missing | `GET {MPSDC}/api/tdr/drcs/{certificate}` | Same missing rule |

Compared fields: certificate, application, owner, plot, rid, flg, samagra, owner_from, owner_to, receipt, file number, actual TDR, transferred TDR, remaining TDR. Document paths are not compared.

| Output status | Meaning |
|---|---|
| MATCH | Fields agree. `on_chain` true |
| MISMATCH | Ledger missing, or `diffs` lists `field`, `tdr`, and `blockchain` |
| NOT_FOUND | TDR does not have the certificate |
| API_FAILURE | `message` names TDR or Blockchain and the HTTP status |

A bad MPSDC key looks like `API_FAILURE` and `Blockchain HTTP 401: Invalid or missing API token`.

## GET /verifications

```http
GET /verifications
GET /verifications?certificate=DRC/2024/00002/Indore
```

List `200`: `{ "count": 1, "verifications": { "<certificate>": { "...phase 1 row..." } } }`.

One missing certificate `404`: `{ "status": "NOT_FOUND", "message": "No stored verification for that certificate" }`.

Reads the scheduler store only.

## GET /verifications.csv

```http
GET /verifications.csv
GET /verifications.csv?onChain=1
```

`200` with `text/csv`. File name `phase1-verifications.csv`, or `phase1-on-chain.csv` when `onChain=1`.

Columns: `certificate_no`, `application_id`, `status`, `on_chain`, `flg`, `chain_action`, `message`, `checked_at`, `diffs`.

`onChain=1` keeps rows whose stored `on_chain` is true, and older rows whose status is `MATCH`.

## POST /run/phase2

Legacy migration. Writes the ledger unless `DRY_RUN=true`.

```http
POST /run/phase2
Content-Type: application/json

{ "applicationId": "TDR202471184557197", "limit": 1, "force": false, "oneShot": false }
```

Empty `applicationId` reads the full TDR application list. `force` true reruns an application that already succeeded. `oneShot` true turns the daily legacy schedule off when this run returns.

Success `200`:

```json
{
  "count": 1,
  "jobs": [
    {
      "application_id": "TDR202471184557197",
      "mode": "legacy",
      "status": "SUCCESS",
      "last_successful_stage": "TRANSFER",
      "last_error": "",
      "stages": {
        "GENERATING_AREA": { "status": "MATCH", "message": "generating area verified" },
        "OWNER_DETAIL": { "status": "MATCH", "message": "verified 1 owner(s)" },
        "DRC_UPLOAD": { "status": "MATCH", "message": "verified 1 DRC(s) (1 generate, 0 update)" },
        "TRANSFER": { "status": "SKIPPED", "message": "no transferable rows" }
      }
    }
  ],
  "run": { "status": "COMPLETED", "extracted": ["TDR202471184557197"], "items": [] }
}
```

If phase 2 is already running, `409` and `{ "status": "FAILED", "message": "Phase 2 is already running" }`.

If TDR cannot return the application list at all, `502` and the TDR error message. No job is stored for that failure.

Internal calls for each application:

| Order | Call | Check | Output if it fails |
|---|---|---|---|
| 1 | `GET {TDR}/GetApplicationList` | Only when no application id was sent. Each `application_id` is listed on the run before work starts | 502, run does not start |
| 2 | `GET {TDR}/GetGeneratingApplicationByApplicationID?applicationid=` | Missing generating area fails the job at `GENERATING_AREA` | Job `FAILED`, `last_error` explains it |
| 3 | `GET {TDR}/GetApplicationDetailByApplicationID?application_id=` | Owners, nested `drc_upload`, and `transfer` are collected | Same, stage `LOAD` |
| 4 | `GET {TDR}/getOwnerDetailByCertificateNo?certificateno=` | Only when the detail has no DRC rows and certificate scan is on | DRC stage `SKIPPED` if still none |
| 5 | `POST {MPSDC}/Agency/InsertGeneratingArea` | Body needs `p_application_id`. HTTP 400 containing `already exists` continues | Stage `API_FAILURE` or `FAILED` |
| 6 | `GET {MPSDC}/Agency/GetApplicationDetails?applicationid=` | Compared with the body just sent | `MISMATCH` stops the job |
| 7 | `POST {MPSDC}/Agency/InsertOwnerDetail` | Requires `ownernm`, `owner_id`, `applicationid`, `land_plot_id`. TDR type `Plot` is sent as `PLOT` | Stops on that owner |
| 8 | `GET {MPSDC}/api/tdr/owners/{ownerId}` then `GET /Agency/GetOwnerDetails` | Name, samagra, mobile, application | `MISMATCH` stops the job |
| 9 | `POST {MPSDC}/Department/DRCUpload` | `flg` must be one of the four flags. Update flags are `TRANSFER_OWNER` and `UTILIZATION_OWNER` | Stops on that certificate |
| 10 | `GET {MPSDC}/Agency/GetDRCDetails?certificateNumber=` | Same field compare as phase 1 | `MISMATCH` stops before transfer |
| 11 | `POST {MPSDC}/User/InsertTransferRequest` | Sent only when a transfer amount is within remaining TDR. No separate read-back | Amount too high is `FAILED` before the POST |

An application already `SUCCESS` is not written again unless `force` is true. The run item status is `SKIPPED` and the message is `Already completed`.

`DRY_RUN=true` skips every POST. Stage status is `DRY_RUN` and the job can still be `SUCCESS`.

## POST /run/phase3

One live application, or a scan for applications that are not already `SUCCESS` in legacy or live mode. Same stage order and same checks as phase 2.

```http
POST /run/phase3
Content-Type: application/json

{
  "applicationId": "TDR202471184557197",
  "ownerIds": ["101"],
  "certificateNos": ["DRC/2024/00002/Indore"],
  "force": false,
  "limit": 1
}
```

`ownerIds` and `certificateNos` may be arrays or comma-separated strings. Any other shape is `400`.

Extra internal reads when those ids are sent:

| Call | Use |
|---|---|
| `GET {TDR}/getOwnerDetailByOwnerID?owner_id=` | Each owner id |
| `GET {TDR}/GetDetailByCertificateNo?certificateNo=` | Each certificate |
| `GET {TDR}/getOwnerDetailByCertificateNo?certificateno=` | Owner rows for that certificate |

The job `mode` is `live`. There is no daily clock for this call. It runs only when this request is sent.

Already-open phase 3 returns `409`. A TDR failure before any application starts returns `502`.

## GET /jobs

```http
GET /jobs
GET /jobs?applicationId=TDR202471184557197&mode=legacy
```

`mode` must be `legacy` or `live`. Anything else is `400`.

List `200`: `{ "count": 1, "jobs": { "legacy:TDR202471184557197": { "...job..." } } }`.

Missing job `404`: `{ "status": "NOT_FOUND", "message": "No stored job for that application" }`.

## GET /runs

```http
GET /runs
```

`200`:

```json
{
  "runs": {
    "phase2": { "status": "RUNNING", "current": "TDR202471184557197", "index": 2, "total": 36, "items": [], "log": [] },
    "phase3": { "status": "IDLE", "message": "No run yet" }
  }
}
```

`items[].status` is `PENDING`, `RUNNING`, `SUCCESS`, `FAILED`, `SKIPPED`, `STOPPED`, or `NOT_STARTED`. `log` is the short history. This is the store of the current run, not a new TDR call.

Poll this while `POST /run/phase2` or `POST /run/phase3` is still open.

## POST /runs/phase2/pause

## POST /runs/phase2/resume

## POST /runs/phase2/stop

Same three paths exist for `phase3`.

```http
POST /runs/phase2/pause
Content-Type: application/json

{}
```

`200` returns the run object. Pause and stop take effect after the owner or certificate already in flight. Resume continues the same run.

No active run: `409` and `Phase 2 has no run to pause`.

## POST /schedule

Saves the legacy daily window. It does not start a run by itself.

```http
POST /schedule
Content-Type: application/json

{
  "legacy": {
    "enabled": true,
    "start": "01:00",
    "hours": 4,
    "stopWhenComplete": true
  }
}
```

`start` is `HH:MM` in Asia/Kolkata. `hours` is 1 to 12. `20` returns `400` and `legacy hours must be from 1 to 12`.

Success `200`:

```json
{
  "schedule": {
    "timezone": "Asia/Kolkata",
    "legacy": {
      "enabled": true,
      "start": "01:00",
      "hours": 4,
      "stopWhenComplete": true,
      "message": "On. Each day at 01:00 for 4 hour(s)."
    }
  },
  "now": "2026-11-10T13:00:00+05:30",
  "legacyWindowOpen": false
}
```

While the window is open and that day's run has not started, the clock calls the same work as `POST /run/phase2` with an empty application id. At the end of the window the running legacy job is stopped after the current step. The next day continues jobs that are not `SUCCESS`. When every extracted application is `SUCCESS` or `SKIPPED` and `stopWhenComplete` is true, `enabled` becomes false.

## GET /schedule

Returns the same object as a successful `POST /schedule`. No TDR or MPSDC call.
