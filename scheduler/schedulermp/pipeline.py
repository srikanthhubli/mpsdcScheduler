"""Phase 2 and phase 3 share one write sequence.

Generating area → verify → owners → verify → DRC upload → verify → transfer.
A mismatch blocks the next stage. An API failure is not stored as a mismatch.
"""

from __future__ import annotations

import json
import logging
import urllib.request
from concurrent.futures import ThreadPoolExecutor, as_completed
from contextvars import ContextVar

from schedulermp.bundle import Bundle
from schedulermp.chain import tx_id
from schedulermp.compare import (
    chain_application_canonical,
    chain_owner_canonical,
    diff_maps,
    drc_canonical,
    generating_canonical,
    owner_canonical,
    unwrap_chain_drc,
)
from schedulermp.http_client import ApiError, is_missing
from schedulermp.mapping import (
    _text,
    chain_action,
    drc_body,
    generating_body,
    lists_from_payload,
    owner_body,
    transfer_body,
    valid_flg,
)
from schedulermp.runs import StopRequested
from schedulermp.store import utc_now

log = logging.getLogger("schedulermp.sync")

STAGES = ("GENERATING_AREA", "OWNER_DETAIL", "DRC_UPLOAD", "TRANSFER")
_RUN = ContextVar("run_control", default=None)


def job_key(mode: str, application_id: str) -> str:
    return f"{mode}:{application_id}"


def _blank_job(mode: str, application_id: str) -> dict:
    return {
        "application_id": application_id,
        "mode": mode,
        "status": "PENDING",
        "current_stage": "",
        "last_successful_stage": "",
        "retry_count": 0,
        "last_error": "",
        "last_attempt_at": "",
        "stages": {},
    }


class SyncService:
    def __init__(self, settings, tdr, chain, store):
        self.settings = settings
        self.tdr = tdr
        self.chain = chain
        self.store = store
        self._index = None
        self._index_lock_built = False

    def certificate_index(self) -> dict[str, dict]:
        if self._index is not None:
            return self._index
        numbers = self.tdr.certificate_numbers()
        index: dict[str, dict] = {}
        log.info("building certificate index for %s certificate(s)", len(numbers))

        def fetch(number: str):
            return number, self.tdr.drc_by_certificate(number)

        workers = max(1, self.settings.phase1_concurrency)
        with ThreadPoolExecutor(max_workers=workers) as pool:
            futures = [pool.submit(fetch, number) for number in numbers]
            for future in as_completed(futures):
                try:
                    number, payload = future.result()
                except ApiError as exc:
                    log.warning("certificate index skip: %s", exc.message)
                    continue
                index[number] = payload
        self._index = index
        log.info("certificate index ready: %s of %s", len(index), len(numbers))
        return index

    def load_bundle(self, application_id: str, owner_ids: list[str], certificate_nos: list[str], scan_certs: bool) -> Bundle:
        bundle = Bundle(application_id)
        self._safe_absorb(bundle, "generating", lambda: self.tdr.generating_by_application(application_id))
        self._safe_absorb(bundle, "application", lambda: self.tdr.application_detail(application_id))
        for owner_id in owner_ids:
            self._safe_absorb(bundle, f"owner {owner_id}", lambda owner_id=owner_id: self.tdr.owner_by_id(owner_id))
        for certificate_no in certificate_nos:
            self._safe_absorb(
                bundle,
                f"certificate {certificate_no}",
                lambda certificate_no=certificate_no: self.tdr.drc_by_certificate(certificate_no),
            )
            self._safe_absorb(
                bundle,
                f"owner certificate {certificate_no}",
                lambda certificate_no=certificate_no: self.tdr.owner_by_certificate(certificate_no),
            )
        if scan_certs and not bundle.drcs:
            for payload in self.certificate_index().values():
                if application_id in _application_ids(payload):
                    bundle.absorb(payload)
        bundle.application_id = bundle.resolved_application_id() or application_id
        return bundle

    def _safe_absorb(self, bundle: Bundle, label: str, fetch) -> None:
        try:
            bundle.absorb(fetch())
        except ApiError as exc:
            log.info("TDR %s unavailable for %s: %s", label, bundle.application_id, exc.message)

    def run_application(
        self,
        mode: str,
        application_id: str,
        owner_ids: list[str] | None = None,
        certificate_nos: list[str] | None = None,
        force: bool = False,
        scan_certs: bool | None = None,
        control=None,
    ) -> dict:
        owner_ids = owner_ids or []
        certificate_nos = certificate_nos or []
        if scan_certs is None:
            scan_certs = self.settings.phase2_scan_certs if mode == "legacy" else self.settings.phase3_scan_certs
        token = _RUN.set(control)
        try:
            return self._run_application(mode, application_id, owner_ids, certificate_nos, force, scan_certs, control)
        finally:
            _RUN.reset(token)

    def _run_application(
        self,
        mode: str,
        application_id: str,
        owner_ids: list[str],
        certificate_nos: list[str],
        force: bool,
        scan_certs: bool,
        control,
    ) -> dict:
        key = job_key(mode, application_id)
        existing = self.store.job(key) or _blank_job(mode, application_id)
        if existing.get("status") == "SUCCESS" and not force:
            log.info("%s %s skipped: already completed", mode, application_id)
            return self._report(control, application_id, existing, "SKIPPED", "Already completed")
        if existing.get("retry_count", 0) >= self.settings.max_retries and existing.get("status") == "FAILED" and not force:
            log.info("%s %s skipped: retry limit %s", mode, application_id, existing.get("retry_count"))
            return self._report(control, application_id, existing, "SKIPPED", "Retry limit reached")

        job = _blank_job(mode, application_id)
        job["retry_count"] = 0 if force else existing.get("retry_count", 0)
        job["last_successful_stage"] = "" if force else existing.get("last_successful_stage", "")
        job["stages"] = {} if force else existing.get("stages") or {}
        job["status"] = "IN_PROGRESS"
        job["last_attempt_at"] = utc_now()
        self.store.save_job(key, job)
        log.info("%s %s started", mode, application_id)

        try:
            _gate()
            _detail("LOAD", "Reading generating area, application, owners, and certificates")
            bundle = self.load_bundle(application_id, owner_ids, certificate_nos, scan_certs)
            loaded = (
                f"{len(bundle.owners)} owners, {len(bundle.drcs)} DRCs, "
                f"{len(bundle.plots)} plots, {len(bundle.transfers)} transfers"
            )
            _detail("LOAD", loaded, log=True)
            log.info("%s %s loaded %s", mode, application_id, loaded)
        except StopRequested:
            log.info("%s %s stopped during load", mode, application_id)
            return self._stopped(key, job, control, application_id)
        except ApiError as exc:
            log.warning("%s %s load failed: %s", mode, application_id, exc.message)
            return self._report(control, application_id, self._fail(key, job, "LOAD", exc.message, exc.retryable))

        start = 0
        if job["last_successful_stage"] in STAGES:
            start = STAGES.index(job["last_successful_stage"]) + 1
        if start:
            log.info("%s %s resumes after %s", mode, application_id, job["last_successful_stage"])

        runners = (
            self._stage_generating,
            self._stage_owners,
            self._stage_drcs,
            self._stage_transfers,
        )
        try:
            for stage, runner in zip(STAGES[start:], runners[start:]):
                _gate()
                job["current_stage"] = stage
                self.store.save_job(key, job)
                _detail(stage, "Started")
                outcome = runner(bundle)
                job["stages"][stage] = outcome
                self._callback(application_id, stage, outcome)
                _detail(stage, f"{outcome['status']}: {outcome.get('message') or ''}", log=True)
                _log_stage(mode, application_id, stage, outcome)
                if outcome["status"] in {"MATCH", "SKIPPED", "DRY_RUN"}:
                    job["last_successful_stage"] = stage
                    job["last_error"] = ""
                    self.store.save_job(key, job)
                    continue
                if outcome["status"] == "MISMATCH":
                    job["status"] = "FAILED"
                    job["last_error"] = outcome.get("message") or "MISMATCH"
                    self.store.save_job(key, job)
                    return self._report(control, application_id, job)
                job["retry_count"] = job.get("retry_count", 0) + 1
                job["status"] = "FAILED"
                job["last_error"] = outcome.get("message") or outcome["status"]
                self.store.save_job(key, job)
                return self._report(control, application_id, job)
        except StopRequested:
            log.info("%s %s stopped during %s", mode, application_id, job.get("current_stage") or "")
            return self._stopped(key, job, control, application_id)

        job["status"] = "SUCCESS"
        job["current_stage"] = job["last_successful_stage"]
        job["retry_count"] = 0
        job["last_error"] = ""
        self.store.save_job(key, job)
        log.info("%s %s finished SUCCESS", mode, application_id)
        return self._report(control, application_id, job)

    def run_legacy_batch(self, application_id: str = "", limit: int = 0, force: bool = False, control=None) -> list[dict]:
        if control:
            control.note(
                f"Using application {application_id}" if application_id else "Reading the TDR application list"
            )
        if application_id:
            apps = [{"application_id": application_id}]
        else:
            apps = self.tdr.application_list()
        if limit:
            apps = apps[:limit]
        ids = [app_id for row in apps if (app_id := _text(row.get("application_id")))]
        log.info("legacy batch %s application(s)%s", len(ids), " force" if force else "")
        if control:
            control.extracted(ids)
        results = []
        for index, app_id in enumerate(ids, 1):
            if control and not control.should_continue():
                log.info("legacy batch stopped after %s application(s)", index - 1)
                break
            if control:
                control.begin(app_id, index)
            results.append(self.run_application("legacy", app_id, force=force, control=control))
        log.info("legacy batch finished %s job(s)", len(results))
        return results

    def run_live_batch(self, limit: int = 0, control=None) -> list[dict]:
        if control:
            control.note("Reading the TDR application list")
        apps = self.tdr.application_list()
        if limit:
            apps = apps[:limit]
        ids = [app_id for row in apps if (app_id := _text(row.get("application_id")))]
        log.info("live batch %s application(s)", len(ids))
        if control:
            control.extracted(ids)
        results = []
        for index, app_id in enumerate(ids, 1):
            if control and not control.should_continue():
                log.info("live batch stopped after %s application(s)", index - 1)
                break
            legacy = self.store.job(job_key("legacy", app_id))
            live = self.store.job(job_key("live", app_id))
            if control:
                control.begin(app_id, index)
            if legacy and legacy.get("status") == "SUCCESS":
                log.info("live %s skipped: phase 2 already completed it", app_id)
                if control:
                    control.finish(app_id, "SKIPPED", "Phase 2 already completed this application", "")
                continue
            if live and live.get("status") == "SUCCESS":
                log.info("live %s skipped: already completed", app_id)
                if control:
                    control.finish(app_id, "SKIPPED", "Already completed", "")
                continue
            results.append(self.run_application("live", app_id, force=False, control=control))
        log.info("live batch finished %s job(s)", len(results))
        return results

    def _stage_generating(self, bundle: Bundle) -> dict:
        if not bundle.generating:
            return _stage("FAILED", "TDR generating area was not returned", retryable=True)
        body = generating_body(bundle.generating, bundle.plots, bundle.lands)
        if not body.get("p_application_id"):
            return _stage("FAILED", "p_application_id is missing from TDR generating area", retryable=False)
        missing_plot = next((row for row in body.get("plotRecords") or [] if not _text(row.get("plot_id"))), None)
        if missing_plot:
            return _stage("FAILED", "A plot record is missing plot_id", retryable=False)
        missing_land = next((row for row in body.get("landRecords") or [] if not _text(row.get("land_id"))), None)
        if missing_land:
            return _stage("FAILED", "A land record is missing land_id", retryable=False)
        if self.settings.dry_run:
            return _stage("DRY_RUN", "InsertGeneratingArea not sent", payload_keys=list(body.keys()))
        try:
            response = self.chain.post("/Agency/InsertGeneratingArea", body)
        except ApiError as exc:
            return _stage("API_FAILURE", exc.message, retryable=exc.retryable)
        status, readback = self.chain.get(
            "/Agency/GetApplicationDetails",
            {"applicationid": body["p_application_id"]},
        )
        if is_missing(status, readback):
            return _stage("MISMATCH", "generating area missing on blockchain", tx=tx_id(response))
        diffs = diff_maps(generating_canonical(body), chain_application_canonical(readback))
        if diffs:
            return _stage("MISMATCH", "generating area differs", diffs=diffs, tx=tx_id(response))
        return _stage("MATCH", "generating area verified", tx=tx_id(response))

    def _stage_owners(self, bundle: Bundle) -> dict:
        if not bundle.owners:
            return _stage("SKIPPED", "no owners on the TDR payload")
        checked = []
        total = len(bundle.owners)
        for index, owner in enumerate(bundle.owners, 1):
            _gate()
            body = owner_body(owner, bundle.application_id, bundle.docs, bundle.multi_owners)
            if not body.get("owner_id") or not body.get("land_plot_id"):
                return _stage("FAILED", "owner is missing owner_id or land_plot_id", retryable=False)
            if not _text(body.get("ownernm")):
                return _stage("FAILED", f"owner {body['owner_id']} is missing ownernm", retryable=False)
            _detail("OWNER_DETAIL", f"Owner {index} of {total} ({body['owner_id']})")
            if self.settings.dry_run:
                checked.append(str(body["owner_id"]))
                continue
            try:
                response = self.chain.post("/Agency/InsertOwnerDetail", body)
            except ApiError as exc:
                return _stage("API_FAILURE", f"owner {body['owner_id']}: {exc.message}", retryable=exc.retryable)
            if hasattr(self.chain, "get_owner"):
                status, readback = self.chain.get_owner(str(body["owner_id"]), body["applicationid"])
            else:
                status, readback = self.chain.get(
                    "/Agency/GetOwnerDetails",
                    {"owner_id": body["owner_id"], "applicationid": body["applicationid"]},
                )
            if is_missing(status, readback):
                return _stage("MISMATCH", f"owner {body['owner_id']} missing on blockchain", tx=tx_id(response))
            diffs = diff_maps(owner_canonical(body, bundle.application_id), chain_owner_canonical(readback))
            if diffs:
                return _stage("MISMATCH", f"owner {body['owner_id']} differs", diffs=diffs, tx=tx_id(response))
            checked.append(str(body["owner_id"]))
        if self.settings.dry_run:
            return _stage("DRY_RUN", "InsertOwnerDetail not sent", owners=checked)
        return _stage("MATCH", f"verified {len(checked)} owner(s)", owners=checked)

    def _stage_drcs(self, bundle: Bundle) -> dict:
        if not bundle.drcs:
            return _stage("SKIPPED", "no DRC rows on the TDR payload")
        checked = []
        total = len(bundle.drcs)
        for index, row in enumerate(bundle.drcs, 1):
            _gate()
            body = drc_body(row, bundle.application_id)
            if not valid_flg(body["flg"]):
                return _stage("FAILED", f"flg {body['flg']} is not a blockchain DRC flag", retryable=False)
            if not body["certificate_no"]:
                return _stage("FAILED", "DRC row has no certificate number", retryable=False)
            _detail("DRC_UPLOAD", f"DRC {index} of {total} ({body['certificate_no']}) {chain_action(body['flg'])}")
            if self.settings.dry_run:
                checked.append(body["certificate_no"])
                continue
            try:
                response = self.chain.post("/Department/DRCUpload", body)
            except ApiError as exc:
                return _stage("API_FAILURE", f"{body['certificate_no']}: {exc.message}", retryable=exc.retryable)
            if hasattr(self.chain, "get_drc"):
                status, readback = self.chain.get_drc(body["certificate_no"])
            else:
                status, readback = self.chain.get(
                    "/Agency/GetDRCDetails",
                    {"certificateNumber": body["certificate_no"]},
                )
            if is_missing(status, readback):
                return _stage(
                    "MISMATCH",
                    f"{body['certificate_no']} missing on blockchain",
                    tx=tx_id(response),
                )
            diffs = diff_maps(drc_canonical(body), drc_canonical(unwrap_chain_drc(readback, body["certificate_no"])))
            if diffs:
                return _stage("MISMATCH", f"{body['certificate_no']} differs", diffs=diffs, tx=tx_id(response))
            checked.append(body["certificate_no"])
        if self.settings.dry_run:
            return _stage("DRY_RUN", _drc_message("DRCUpload not sent", bundle.drcs), certificates=checked)
        return _stage("MATCH", _drc_message(f"verified {len(checked)} DRC(s)", bundle.drcs), certificates=checked)

    def _stage_transfers(self, bundle: Bundle) -> dict:
        built = []
        for row in bundle.transfers:
            certificate = _text(row.get("certificate_no") or row.get("drc_certificate_no"))
            transferor = row.get("transferor_owner_id") or row.get("owner_from")
            if not certificate and bundle.drcs:
                certificate = _text(
                    bundle.drcs[0].get("certificate_no") or bundle.drcs[0].get("drc_certificate_no")
                )
            if not transferor and bundle.drcs:
                transferor = bundle.drcs[0].get("owner_id")
            body = transfer_body(row, bundle.application_id, certificate, transferor)
            if body and body.get("transfer_id"):
                params = body.get("param_array") or [{}]
                first = params[0] if params and isinstance(params[0], dict) else {}
                requested = _number(first.get("trn_value_tdr"))
                if requested <= 0:
                    continue
                remaining = _remaining_for(bundle, body.get("certificate_no"))
                if remaining is not None and requested > remaining:
                    return _stage(
                        "FAILED",
                        f"Transfer amount {requested} exceeds available TDR amount {remaining}",
                        retryable=False,
                    )
                built.append(body)
        if not built:
            return _stage("SKIPPED", "no transferable rows")
        sent = []
        total = len(built)
        for index, body in enumerate(built, 1):
            _gate()
            _detail("TRANSFER", f"Transfer {index} of {total} ({body['transfer_id']})")
            if self.settings.dry_run:
                sent.append(body["transfer_id"])
                continue
            try:
                response = self.chain.post("/User/InsertTransferRequest", body)
            except ApiError as exc:
                return _stage("API_FAILURE", f"{body['transfer_id']}: {exc.message}", retryable=exc.retryable)
            sent.append(tx_id(response) or body["transfer_id"])
        if self.settings.dry_run:
            return _stage("DRY_RUN", "InsertTransferRequest not sent", transfers=sent)
        return _stage("MATCH", f"submitted {len(sent)} transfer(s)", transfers=sent)

    def _stopped(self, key: str, job: dict, control, application_id: str) -> dict:
        job["status"] = "STOPPED"
        job["last_error"] = "Stopped by operator"
        self.store.save_job(key, job)
        return self._report(control, application_id, job)

    def _report(self, control, application_id: str, job: dict, status: str = "", message: str = "") -> dict:
        if control:
            control.finish(
                application_id,
                status or job.get("status") or "",
                message or _job_message(job),
                job.get("current_stage") or job.get("last_successful_stage") or "",
            )
        return job

    def _fail(self, key: str, job: dict, stage: str, message: str, retryable: bool) -> dict:
        job["current_stage"] = stage
        job["status"] = "FAILED"
        job["retry_count"] = job.get("retry_count", 0) + 1
        job["last_error"] = message
        job["stages"][stage] = _stage("API_FAILURE", message, retryable=retryable)
        self.store.save_job(key, job)
        return job

    def _callback(self, application_id: str, stage: str, outcome: dict) -> None:
        if not self.settings.callback_url:
            return
        status = "SUCCESS" if outcome["status"] in {"MATCH", "SKIPPED", "DRY_RUN"} else "FAILED"
        payload = {
            "application_id": application_id,
            "stage": stage,
            "status": status,
            "blockchain_tx_id": outcome.get("tx_id") or "",
            "timestamp": utc_now(),
            "retryable": bool(outcome.get("retryable")),
            "error_code": None if status == "SUCCESS" else outcome["status"],
            "message": outcome.get("message") or "",
        }
        data = json.dumps(payload).encode("utf-8")
        request = urllib.request.Request(
            self.settings.callback_url,
            data=data,
            headers={"Content-Type": "application/json", "Accept": "application/json"},
            method="POST",
        )
        try:
            with urllib.request.urlopen(request, timeout=self.settings.http_timeout_sec):
                return
        except Exception as exc:  # callback must not hide the blockchain result
            log.warning("migration callback failed: %s", exc)
            outcome["callback_error"] = str(exc)


def _log_stage(mode: str, application_id: str, stage: str, outcome: dict) -> None:
    message = outcome.get("message") or ""
    status = outcome.get("status") or ""
    fields = [item.get("field") for item in outcome.get("diffs") or [] if isinstance(item, dict) and item.get("field")]
    suffix = f" fields={','.join(str(field) for field in fields[:12])}" if fields else ""
    line = "%s %s %s %s: %s%s"
    if status in {"FAILED", "API_FAILURE", "MISMATCH"}:
        log.warning(line, mode, application_id, stage, status, message, suffix)
        return
    log.info(line, mode, application_id, stage, status, message, suffix)


def _drc_message(prefix: str, rows: list) -> str:
    updates = 0
    generates = 0
    for row in rows:
        action = chain_action(_text(row.get("flg")))
        if action == "update":
            updates += 1
        elif action == "generate":
            generates += 1
    return f"{prefix} ({generates} generate, {updates} update)"


def _gate() -> None:
    control = _RUN.get()
    if control is not None and not control.should_continue():
        raise StopRequested()


def _detail(stage: str, message: str, log: bool = False) -> None:
    control = _RUN.get()
    if control is None:
        return
    control.detail(control.state.get("current") or "", stage, message, log=log)


def _job_message(job: dict) -> str:
    if job.get("last_error"):
        return job["last_error"]
    stages = job.get("stages") or {}
    parts = [f"{name} {row.get('status')}" for name, row in stages.items()]
    return ", ".join(parts) or job.get("status") or ""


def _number(value) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return 0.0


def _remaining_for(bundle: Bundle, certificate_no: str) -> float | None:
    wanted = _text(certificate_no)
    for row in bundle.drcs:
        cert = _text(row.get("certificate_no") or row.get("drc_certificate_no"))
        if cert != wanted:
            continue
        raw = row.get("remaining_value_tdr")
        if raw is None or raw == "":
            return None
        return _number(raw)
    return None


def _stage(status: str, message: str, **extra) -> dict:
    record = {"status": status, "message": message, "at": utc_now()}
    record.update(extra)
    if "tx" in record:
        record["tx_id"] = record.pop("tx")
    return record


def _application_ids(payload: dict) -> set[str]:
    ids = set()
    for row in lists_from_payload(
        payload,
        (
            "certificate_details",
            "drc_upload",
            "drcs",
            "generatingarea",
            "generating_area",
            "project_details",
            "owner_details",
            "owners",
            "owner",
        ),
    ):
        for key in ("application_id", "applicationid", "p_application_id", "applicationID"):
            if row.get(key):
                ids.add(_text(row[key]))
    return ids
