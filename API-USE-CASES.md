# API use cases

TDR is the system of record. The scheduler only reads TDR. It never writes the TDR database. Blockchain writes go to the MPSDC MP-TDR API. Phase 1 does not write.

Legacy migration is started once a day from the Run screen. It may keep running only for the number of hours selected there, then continues the next day until the list is complete.

TDR base: `https://gisdemo.mp.gov.in/TDR/TDRService/api/DataSharing`

MPSDC base: `https://mpbsp-uat.mp.gov.in`

Business MPSDC calls send `X-API-Key` and the query `channel=mptdr`, `org=mpgovdepartment`, `peer=peer0-mpgovdepartment`.

## Phase 1 — check that a DRC on TDR matches the ledger

Use this to reconcile certificates. It does not create or update anything.

| Step | System | Call | Use |
|---|---|---|---|
| List certificates | TDR | `GET /GetDRCNoList` | Source list when the screen or request leaves the certificate blank |
| Read the current DRC | TDR | `GET /GetDetailByCertificateNo?certificateNo=` | Latest TDR certificate, owner, plot, values, and `flg` |
| Read the ledger DRC | MPSDC | `GET /Agency/GetDRCDetails?certificateNumber=` | Comparison source. This legacy read keeps `owner_from` and `owner_to` |
| Fallback read | MPSDC | `GET /api/tdr/drcs/{certificateNumber}` | Used only when the legacy read is missing |

A missing ledger record is `MISMATCH` / `MISSING_ON_BLOCKCHAIN`. A TDR 404 is `NOT_FOUND`. A failed call is `API_FAILURE`, not a mismatch.

Compared fields: certificate, application, owner, plot, rid, flg, samagra, owner_from, owner_to, receipt, file number, actual TDR, transferred TDR, remaining TDR. Document paths are not compared.

The screen stores each row. **Export all** and **Export on chain** download that store. `on_chain=yes` means the ledger had the certificate. `chain_action` says whether that `flg` would create or update a DRC.

## Phase 2 — copy an existing application onto the ledger

Use this for legacy migration. The screen or `POST /run/phase2` walks `GetApplicationList`, or one `applicationId`.

| Order | System | Call | Use |
|---|---|---|---|
| 1 | TDR | `GET /GetApplicationList` | Application ids to migrate |
| 2 | TDR | `GET /GetGeneratingApplicationByApplicationID?applicationid=` | Generating area, plots, and lands |
| 3 | TDR | `GET /GetApplicationDetailByApplicationID?application_id=` | Owners, nested DRCs, transfers, and documents |
| 4 | TDR | `GET /getOwnerDetailByCertificateNo?certificateno=` | Used when the application detail has no DRC rows and certificate scan is on |
| 5 | MPSDC | `POST /Agency/InsertGeneratingArea` | Create the application area. An “already exists” response is treated as success |
| 6 | MPSDC | `GET /Agency/GetApplicationDetails?applicationid=` | Read-back. A field difference stops the job |
| 7 | MPSDC | `POST /Agency/InsertOwnerDetail` | One call per owner. `ownernm`, `owner_id`, `applicationid`, and `land_plot_id` are required. TDR owner type `Plot` is sent as `PLOT` |
| 8 | MPSDC | `GET /api/tdr/owners/{ownerId}` | Owner read-back. Falls back to `GET /Agency/GetOwnerDetails` |
| 9 | MPSDC | `POST /Department/DRCUpload` | One call per certificate. `flg` selects create or update. See the flag table |
| 10 | MPSDC | `GET /Agency/GetDRCDetails?certificateNumber=` | DRC read-back |
| 11 | MPSDC | `POST /User/InsertTransferRequest` | Sent only when TDR has a transfer whose amount does not exceed remaining TDR. There is no separate transfer read-back |

A mismatch stops the next stage. The job stays `FAILED` until it is run again, with Force if it had already succeeded.

## Phase 3 — send one live application

Use this when TDR has a current application that should be written in the same order as phase 2. `POST /run/phase3` takes `applicationId`, optional `ownerIds`, and optional `certificateNos`.

| Step | System | Call | Use |
|---|---|---|---|
| Scope | TDR | `GET /GetApplicationList` | Used only when no application id is given. Applications already completed in phase 2 or phase 3 are skipped |
| Generating area | TDR | `GET /GetGeneratingApplicationByApplicationID?applicationid=` | Same write as phase 2 |
| One owner | TDR | `GET /getOwnerDetailByOwnerID?owner_id=` | Used for each owner id passed on the request, and for owners inside the application detail |
| Certificate bundle | TDR | `GET /GetDetailByCertificateNo` and `GET /getOwnerDetailByCertificateNo` | Used for each certificate passed on the request |
| Writes and read-backs | MPSDC | Same four writes as phase 2 | Same stop-on-mismatch rule |

## DRC flag: create or update

MPSDC `POST /Department/DRCUpload` reads `flg` and chooses the ledger operation. The scheduler sends the TDR value. It does not write a flag back to the TDR database.

| `flg` from TDR | MPSDC mode | Use |
|---|---|---|
| `FIRST_OWNER` | generate | First DRC for that owner |
| `TRANSFEREE_OWNER` | generate | New DRC for the owner who received area |
| `TRANSFER_OWNER` | update | Existing DRC changes because area was transferred |
| `UTILIZATION_OWNER` | update | Existing DRC changes because area was utilized |

If a generate flag is sent for a certificate that is already on the ledger, MPSDC switches that call to an update. The scheduler still records the TDR flag. Phase 1 shows it as `chain_action`. Phase 2 and phase 3 log each certificate as `generate` or `update`, and the stage message counts both.

Any other `flg` fails the DRC stage before the write. The allowed set is only the four values above.

## What is intentionally not called

The scheduler does not call a TDR callback. `TDR_CALLBACK_URL` is sent only when that variable is set, because TDR has not published the callback.

Phase 1 does not call `InsertGeneratingArea`, `InsertOwnerDetail`, `DRCUpload`, or `InsertTransferRequest`.

Health on the MPSDC host is open. Every business route needs the API key.
