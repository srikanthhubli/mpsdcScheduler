# How the scheduler runs

The scheduler is one Python process. It serves the admin screen and the HTTP API on the same port. It reads TDR and writes the MPSDC blockchain API. It never writes the TDR database.

Times for the legacy daily run use Asia/Kolkata.

## Who starts work

```mermaid
flowchart TD
  admin[Admin on the Run screen] --> phase1[Phase 1 check]
  admin --> phase2[Phase 2 legacy run]
  admin --> phase3[Phase 3 one live application]
  clock[Daily clock] --> window{Legacy schedule on and inside today's window?}
  window -->|Not started today| phase2
  window -->|Window has ended while a run is still going| stop[Stop after the current owner or certificate]
  stop --> nextDay[Next day continues applications that are not on the chain]
  phase2 --> done{Every application succeeded?}
  done -->|Yes and turn-off is checked| off[Legacy schedule turns off]
  done -->|No| nextDay
```

## Phase 1, one certificate

```mermaid
flowchart TD
  list[GET TDR GetDRCNoList when no certificate is given] --> one[GET TDR GetDetailByCertificateNo]
  one --> tdrFail{TDR returned the certificate?}
  tdrFail -->|No| notFound[NOT_FOUND]
  tdrFail -->|Call failed| apiFail[API_FAILURE]
  tdrFail -->|Yes| chain[GET MPSDC GetDRCDetails]
  chain --> missing{Ledger has the certificate?}
  missing -->|No| mismatch[MISMATCH MISSING_ON_BLOCKCHAIN]
  missing -->|Call failed| apiFail
  missing -->|Yes| compare[Compare certificate, owner, plot, values, and flg]
  compare --> same{Fields match?}
  same -->|Yes| match[MATCH and on chain]
  same -->|No| differ[MISMATCH with a field list]
```

Phase 1 does not write to the blockchain.

## Phase 2 and phase 3, one application

Both use the same write order. A mismatch or a failed call stops the next stage. An "already exists" response from MPSDC is treated as success and the stage still reads the record back.

```mermaid
flowchart TD
  read[Read TDR generating area, application detail, owners, and certificates] --> area[POST InsertGeneratingArea]
  area --> areaRead[GET GetApplicationDetails]
  areaRead --> owners[POST InsertOwnerDetail for each owner]
  owners --> ownerRead[GET owner by id]
  ownerRead --> drc[POST DRCUpload for each certificate]
  drc --> drcRead[GET GetDRCDetails]
  drcRead --> transfer{TDR has a transfer within the remaining area?}
  transfer -->|No| skipped[TRANSFER SKIPPED]
  transfer -->|Yes| send[POST InsertTransferRequest]
  areaRead --> stop{Read-back matches?}
  ownerRead --> stop
  drcRead --> stop
  stop -->|No| failed[Job FAILED and the next stage is not called]
  stop -->|Yes| next[Next stage]
```

`flg` on each DRC tells MPSDC what to do:

| flg | Ledger action |
|---|---|
| FIRST_OWNER | generate |
| TRANSFEREE_OWNER | generate |
| TRANSFER_OWNER | update |
| UTILIZATION_OWNER | update |

If a generate flag is sent for a certificate that is already on the ledger, MPSDC updates that certificate. The scheduler still records the TDR flag.

## What each result means

| Result | Meaning |
|---|---|
| MATCH | TDR and the ledger agree |
| MISMATCH | A field differs, or the ledger has no record. The next stage does not run |
| API_FAILURE | TDR or MPSDC did not return usable data. This is not a field mismatch |
| NOT_FOUND | TDR has no such certificate |
| SKIPPED | Nothing to send, or the application was already completed |
| DRY_RUN | The body was built and the blockchain write was not sent |
| SUCCESS | Every stage was MATCH, SKIPPED, or DRY_RUN |
| FAILED | A stage stopped the job. `last_error` has the reason |
| STOPPED | An operator or the end of the daily window stopped the run. The next run continues after the last successful stage |
