# Test the TDR scheduler

Use this on a server that can reach both TDR DataSharing and the MPSDC blockchain API. One process serves the screen and the API.

How the stages move: [FLOW.md](FLOW.md).

The URL, body, internal calls, checks, and output for every scheduler API: [API-CONTRACT.md](API-CONTRACT.md).

## 1. Start

```bash
cd scheduler
cp .env.example .env
```

Set `BLOCKCHAIN_API_KEY` in `.env`. Leave `PHASE1_ENABLED`, `PHASE2_ENABLED`, and `PHASE3_ENABLED` as `false` while clicking through tests. Set `DRY_RUN=true` for the first phase 2 and phase 3 pass.

```bash
python3 -m schedulermp serve
```

Open `http://<server>:8088/`. Sign in with `ADMIN_USERNAME` and `ADMIN_PASSWORD`. The sample values are `admin` and `admin`.

Pass: the status pill reads **online**.

Fail: a red banner names the scheduler URL. The process is not running, or the browser is not pointed at that process.

## 2. Screen checks

Do these in order. The expected result is the pass line.

1. **Overview.** Pass: four counts render, and the two charts render even when every count is 0. The text says whether the phase 1 check and the legacy daily schedule are on.
2. **Run, legacy schedule.** Set start `01:00`, hours `4`, leave Enable unchecked, leave "Turn off when the whole list is complete" checked, and save. Pass: the line under the button says the legacy daily schedule is off. Hours `20` is an error. Pass for that case: the banner says `legacy hours must be from 1 to 12`.
3. **Run, phase 1.** Certificate `DRC/2024/00002/Indore`, limit `1`. Pass: the screen moves to Verifications. Status is `MATCH`, `MISMATCH`, `NOT_FOUND`, or `API_FAILURE`. The Flag and Chain columns are filled when TDR returned the certificate. Open Diff when the status is `MISMATCH`.
4. **Verifications export.** Export all, then Export on chain. Pass: the browser downloads `phase1-verifications.csv` and `phase1-on-chain.csv`. The on-chain file has only rows found on the ledger.
5. **Run, phase 2.** Application `TDR202471184557197`, limit `1`, Force off. Pass: the phase 2 card lists that application id, then each stage, and ends `COMPLETED` or shows `FAILED` with a reason. Pause is enabled only while the status is running. Stop leaves later ids as `NOT_STARTED`.
6. **One shot.** Check "Run this list once and turn the daily legacy schedule off" only when you intend to disable the daily schedule. Pass: after the run, the legacy schedule line says it is off.
7. **Run, phase 3.** Same application id, owner `101`, certificate `DRC/2024/00002/Indore`. Pass: the phase 3 card shows that one id. Jobs, mode `live`, shows the four stages.
8. **Sign out.** Pass: the login card returns. The next screen action says `Login required`.

Do not run phase 1 with an empty certificate and limit `0` on the first try. That walks every certificate and holds the request until it finishes.

With `DRY_RUN=true`, phase 2 and phase 3 stage messages say the blockchain body was not sent. With `DRY_RUN=false`, `MATCH` means the write was read back.

## 3. Postman checks

Import `scheduler/postman/TDR-Scheduler.postman_collection.json`. Set `baseUrl` to `http://<server>:8088`.

| Step | Request | Pass |
|---|---|---|
| 1 | Login | `200`, body has `token`. Later requests send `Authorization: Bearer {{token}}` |
| 2 | Health without Login | `401`, message `Login required` |
| 3 | Health after Login | `200`, `{ "status": "ok" }` |
| 4 | Status | `200`, counts and the legacy schedule |
| 5 | Run phase 1 with one certificate and limit 1 | `200`, `summary.total` is 1. Then List verifications shows that certificate |
| 6 | One verification with a certificate you have not run | `404`, message `No stored verification for that certificate` |
| 7 | Export phase 1 CSV | `200`, CSV header starts with `certificate_no,application_id,status,on_chain` |
| 8 | Run phase 2 with one application and limit 1 | `200` when idle. While it is open, Phase runs shows `extracted` and `current`. A second Run phase 2 before it finishes is `409` |
| 9 | Pause phase 2, then Resume phase 2 | `200` while a run is active. Pause when nothing is running is `409` |
| 10 | One legacy job | `200` after the run, `mode` is `legacy` |
| 11 | Run phase 3 with application, owner, and certificate | `200`, job `mode` is `live` |
| 12 | Save schedule with hours 4 | `200`, message names the start time and the hours |
| 13 | Save schedule with hours 20 | `400`, message `legacy hours must be from 1 to 12` |

Send `limit` as the text `many`. Pass: `400` and `limit must be a whole number`. The connection stays open and the body is JSON.

## 4. How to read a failure

| What you see | What it means | What to do |
|---|---|---|
| Banner cannot reach the scheduler | Nothing is listening on that URL | Start `python3 -m schedulermp serve` and open that same host and port |
| `Login required` | The token is missing | Run Login again |
| `Blockchain HTTP 401` | The API key was rejected | Set `BLOCKCHAIN_API_KEY` and restart the process |
| `TDR connection failed` or `Blockchain connection failed` | The host did not answer. `retryable` is true | Check the server can open that host, then run the same request again |
| `returned a body that is not JSON` | The upstream host returned HTML or a gateway page | Read the message fragment and check the gateway |
| Row `API_FAILURE` | That certificate or stage failed. The rest of a phase 1 batch can still be stored | Read `message`. Do not treat it as a field mismatch |
| Row `MISMATCH` | The ledger is missing or a field differs | Open Diff. The next phase 2 or phase 3 stage does not run |
| Job `FAILED` | `last_error` is the reason | Fix that stage. Run again. Completed stages are skipped until Force is checked |
| `409` Phase 2 is already running | A legacy run is in progress | Wait, or Stop it, then start again |
