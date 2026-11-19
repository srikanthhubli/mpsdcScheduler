"""Phase 1: scheduled DRC verification only. No blockchain writes."""

from __future__ import annotations

import logging
import threading
from concurrent.futures import ThreadPoolExecutor, as_completed

from schedulermp.compare import (
    chain_application_parts,
    chain_owner_parts,
    describe_diffs,
    diff_maps,
    drc_parts,
    generating_parts,
    owner_parts,
    unwrap_chain_drc,
)
from schedulermp.http_client import ApiError, is_missing
from schedulermp.mapping import _text, chain_action, drc_body, lists_from_payload
from schedulermp.store import utc_now

log = logging.getLogger("schedulermp.phase1")


def verify_certificate(tdr, chain, certificate_no: str) -> dict:
    try:
        tdr_body = tdr.drc_by_certificate(certificate_no)
    except ApiError as exc:
        return _result(
            "API_FAILURE",
            exc.message,
            retryable=exc.retryable,
        )

    status_text = _text(tdr_body.get("status")).lower()
    rows = lists_from_payload(tdr_body, ("certificate_details", "drc_upload", "drcs"))
    matched = [
        row
        for row in rows
        if _text(row.get("drc_certificate_no") or row.get("certificate_no") or row.get("certificateNumber"))
        == certificate_no
    ]
    if status_text in {"failed", "error", "not_found"} or not matched:
        if "not found" in _text(tdr_body.get("message")).lower() or not matched:
            return _result("NOT_FOUND", tdr_body.get("message") or "certificate not found in TDR")
        return _result("API_FAILURE", tdr_body.get("message") or "TDR DRC read failed", retryable=True)

    tdr_api = "GET /GetDetailByCertificateNo"
    first = drc_body(matched[0])
    application_id = _text(first.get("applicationid") or first.get("application_id"))
    flg = _text(first.get("flg")).upper()
    action = chain_action(flg)
    records = []
    try:
        status, chain_body, api = _chain_drc(chain, certificate_no)
    except ApiError as exc:
        records.append(_record("DRC", certificate_no, "API_FAILURE", exc.message, blockchain_api="GET /Agency/GetDRCDetails"))
        chain_rows = []
        api = "GET /Agency/GetDRCDetails"
        drc_failed = True
        drc_missing = False
    else:
        drc_failed = False
        drc_missing = is_missing(status, chain_body)
        chain_rows = [] if drc_missing else _chain_drc_rows(chain_body, certificate_no)
    for row in matched:
        if drc_failed:
            break
        body = drc_body(row, application_id)
        label = f"DRC owner {body.get('owner_id') or ''}".strip()
        if drc_missing or not chain_rows:
            records.append(_missing_record("DRC", label, certificate_no, tdr_api, api))
            continue
        counterpart = _match_drc(body, chain_rows)
        if counterpart is None:
            records.append(_missing_record("DRC", label, certificate_no, tdr_api, api))
            continue
        expected, tdr_sources = drc_parts(body)
        actual, chain_sources = drc_parts(counterpart)
        diffs = diff_maps(expected, actual, api, tdr_api, tdr_sources, chain_sources)
        records.append(_compared_record("DRC", label, diffs, tdr_api, api))

    for owner in lists_from_payload(tdr_body, ("owner_details", "owners", "owner")):
        owner_id = _text(owner.get("owner_id"))
        if not owner_id:
            continue
        label = f"Owner {owner_id}"
        try:
            owner_status, owner_body, owner_api = _chain_owner(chain, owner_id, application_id)
        except ApiError as exc:
            records.append(_record("Owner", label, "API_FAILURE", exc.message, blockchain_api="GET /Agency/GetOwnerDetails"))
            continue
        if is_missing(owner_status, owner_body):
            records.append(_missing_record("Owner", label, owner_id, tdr_api, owner_api))
            continue
        expected, tdr_sources = owner_parts(owner, application_id)
        actual, chain_sources = chain_owner_parts(owner_body)
        diffs = diff_maps(expected, actual, owner_api, tdr_api, tdr_sources, chain_sources)
        records.append(_compared_record("Owner", label, diffs, tdr_api, owner_api))

    project_rows = lists_from_payload(tdr_body, ("project_details", "generatingarea", "generating_area"))
    if project_rows and application_id:
        label = f"Generating area {application_id}"
        project_api = "GET /Agency/GetApplicationDetails"
        try:
            project_status, project_body = chain.get("/Agency/GetApplicationDetails", {"applicationid": application_id})
        except ApiError as exc:
            records.append(_record("Generating area", label, "API_FAILURE", exc.message, blockchain_api=project_api))
        else:
            if is_missing(project_status, project_body):
                records.append(_missing_record("Generating area", label, application_id, tdr_api, project_api))
            else:
                expected, tdr_sources = generating_parts(project_rows[0])
                actual, chain_sources = chain_application_parts(project_body)
                diffs = diff_maps(expected, actual, project_api, tdr_api, tdr_sources, chain_sources)
                records.append(_compared_record("Generating area", label, diffs, tdr_api, project_api))

    return _bundle_result(records, application_id, flg, action, drc_missing is False and bool(chain_rows))


def run_phase1(tdr, chain, store, certificate_no: str = "", limit: int = 0, concurrency: int = 4, control=None) -> dict:
    if certificate_no:
        numbers = [certificate_no]
    else:
        numbers = tdr.certificate_numbers()
    if limit:
        numbers = numbers[:limit]
    if control:
        control.extracted(numbers, "certificate")
        for number in numbers:
            log.info("phase 1 queued %s", number)

    results = []
    workers = max(1, concurrency)
    log.info("phase 1 checking %s certificate(s)", len(numbers))
    order = {"n": 0}
    order_lock = threading.Lock()

    def one(number: str):
        if control and not control.should_continue():
            log.info("phase 1 %s not started", number)
            return None
        with order_lock:
            order["n"] += 1
            index = order["n"]
        if control:
            control.begin(number, index)
        record = verify_certificate(tdr, chain, number)
        store.save_verification(number, record)
        status = record["status"]
        message = record.get("message") or ""
        log.info(
            "phase 1 %s %s flg=%s action=%s on_chain=%s: %s",
            number,
            status,
            record.get("flg") or "",
            record.get("chain_action") or "",
            record.get("on_chain"),
            message,
        )
        if control:
            control.finish(number, status, message, record.get("chain_action") or "")
        return record

    with ThreadPoolExecutor(max_workers=workers) as pool:
        futures = [pool.submit(one, number) for number in numbers]
        for future in as_completed(futures):
            record = future.result()
            if record:
                results.append(record)

    summary = {"total": len(results), "MATCH": 0, "MISMATCH": 0, "NOT_FOUND": 0, "API_FAILURE": 0}
    for record in results:
        summary[record["status"]] = summary.get(record["status"], 0) + 1
    stopped = bool(control and control._stop.is_set())
    log.info(
        "phase 1 finished total=%s match=%s mismatch=%s not_found=%s api_failure=%s stopped=%s",
        summary["total"],
        summary["MATCH"],
        summary["MISMATCH"],
        summary["NOT_FOUND"],
        summary["API_FAILURE"],
        stopped,
    )
    return {"summary": summary, "results": results, "stopped": stopped}


def _chain_drc_rows(body: dict, certificate_no: str) -> list[dict]:
    data = body.get("data") if isinstance(body, dict) else None
    wanted = _text(certificate_no)
    if isinstance(data, list):
        matched = [
            item
            for item in data
            if isinstance(item, dict)
            and _text(item.get("certificate_no") or item.get("certificateNumber") or item.get("drcID")) == wanted
        ]
        return matched or [item for item in data if isinstance(item, dict)]
    row = unwrap_chain_drc(body, certificate_no)
    return [row] if row else []


def _match_drc(body: dict, chain_rows: list[dict]) -> dict | None:
    owner = _text(body.get("owner_id"))
    for row in chain_rows:
        chain_owner = _text(row.get("owner_id") or row.get("currentOwnerID"))
        if owner and chain_owner == owner:
            return row
    if len(chain_rows) == 1:
        chain_owner = _text(chain_rows[0].get("owner_id") or chain_rows[0].get("currentOwnerID"))
        if not chain_owner or chain_owner == owner:
            return chain_rows[0]
    return None


def _chain_owner(chain, owner_id: str, application_id: str) -> tuple[int, dict, str]:
    default = "GET /Agency/GetOwnerDetails"
    if hasattr(chain, "get_owner"):
        result = chain.get_owner(owner_id, application_id)
        if isinstance(result, tuple) and len(result) >= 3:
            return result[0], result[1], result[2] or default
        status, body = result
        return status, body, default
    status, body = chain.get(default.split(" ", 1)[1], {"owner_id": owner_id, "applicationid": application_id})
    return status, body, default


def _record(kind: str, label: str, status: str, message: str, diffs: list | None = None, **extra) -> dict:
    record = {"kind": kind, "label": label, "status": status, "message": message, "diffs": diffs or []}
    record.update(extra)
    return record


def _missing_record(kind: str, label: str, received: str, tdr_api: str, blockchain_api: str) -> dict:
    return _record(
        kind,
        label,
        "MISMATCH",
        "missing on blockchain",
        diffs=[{
            "field": "record",
            "tdr": received,
            "blockchain": "",
            "tdr_field": kind,
            "tdr_received": received,
            "tdr_api": tdr_api,
            "blockchain_field": kind,
            "blockchain_received": "",
            "blockchain_api": blockchain_api,
            "record": label,
        }],
        tdr_api=tdr_api,
        blockchain_api=blockchain_api,
    )


def _compared_record(kind: str, label: str, diffs: list, tdr_api: str, blockchain_api: str) -> dict:
    for item in diffs:
        item["record"] = label
    if diffs:
        detail = describe_diffs(diffs)
        message = f"differs. {detail}" if detail else "differs"
        status = "MISMATCH"
    else:
        message = "matches"
        status = "MATCH"
    return _record(kind, label, status, message, diffs, tdr_api=tdr_api, blockchain_api=blockchain_api)


def _bundle_result(records: list, application_id: str, flg: str, action: str, on_chain: bool) -> dict:
    diffs = []
    for record in records:
        diffs.extend(record.get("diffs") or [])
    statuses = [record["status"] for record in records]
    if any(status == "MISMATCH" for status in statuses):
        status = "MISMATCH"
    elif any(status == "API_FAILURE" for status in statuses):
        status = "API_FAILURE"
    elif not records:
        status = "NOT_FOUND"
    else:
        status = "MATCH"
    parts = [f"{record['label']}: {record['message']}" for record in records if record["status"] != "MATCH"]
    if parts:
        message = "; ".join(parts)
    else:
        message = f"{len(records)} record(s) match"
    return _result(
        status,
        message,
        application_id=application_id,
        flg=flg,
        chain_action=action,
        on_chain=on_chain,
        records=records,
        diffs=diffs,
    )


def _chain_drc(chain, certificate_no: str) -> tuple[int, dict, str]:
    default = "GET /Agency/GetDRCDetails"
    if hasattr(chain, "get_drc"):
        result = chain.get_drc(certificate_no)
        if isinstance(result, tuple) and len(result) >= 3:
            return result[0], result[1], result[2] or default
        status, body = result
        return status, body, default
    status, body = chain.get("/Agency/GetDRCDetails", {"certificateNumber": certificate_no})
    return status, body, default


def _result(status: str, message: str, **extra) -> dict:
    record = {
        "status": status,
        "message": message,
        "checked_at": utc_now(),
        "diffs": extra.get("diffs", []),
        "flg": extra.get("flg", ""),
        "chain_action": extra.get("chain_action", ""),
        "on_chain": bool(extra.get("on_chain")),
    }
    record.update(extra)
    return record


def verifications_csv(rows: dict) -> str:
    import csv
    import io

    fields = [
        "certificate_no",
        "application_id",
        "status",
        "on_chain",
        "flg",
        "chain_action",
        "message",
        "checked_at",
        "diffs",
    ]
    buffer = io.StringIO()
    writer = csv.DictWriter(buffer, fieldnames=fields, extrasaction="ignore")
    writer.writeheader()
    for certificate, row in rows.items():
        item = dict(row)
        item["certificate_no"] = item.get("certificate_no") or certificate
        item["on_chain"] = "yes" if item.get("on_chain") or item.get("status") == "MATCH" else "no"
        diffs = item.get("diffs") or []
        item["diffs"] = "; ".join(
            f"{diff.get('field')}: tdr {diff.get('tdr_field') or diff.get('field')}={diff.get('tdr_received', diff.get('tdr'))} via {diff.get('tdr_api') or ''}; blockchain {diff.get('blockchain_field') or diff.get('field')}={diff.get('blockchain_received', diff.get('blockchain'))} via {diff.get('blockchain_api') or ''}"
            for diff in diffs
            if isinstance(diff, dict)
        )
        writer.writerow(item)
    return buffer.getvalue()
