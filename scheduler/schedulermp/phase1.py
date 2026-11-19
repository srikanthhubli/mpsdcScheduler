"""Phase 1: scheduled DRC verification only. No blockchain writes."""

from __future__ import annotations

import logging
import threading
from concurrent.futures import ThreadPoolExecutor, as_completed

from schedulermp.compare import describe_diffs, diff_maps, drc_parts, unwrap_chain_drc
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
    expected, tdr_sources = drc_parts(drc_body(matched[0]))
    flg = expected.get("flg") or ""
    action = chain_action(flg)
    try:
        status, chain_body, api = _chain_drc(chain, certificate_no)
    except ApiError as exc:
        return _result("API_FAILURE", exc.message, retryable=exc.retryable, application_id=expected["application_id"], flg=flg, chain_action=action, on_chain=False)

    if is_missing(status, chain_body):
        return _result(
            "MISMATCH",
            "MISSING_ON_BLOCKCHAIN",
            application_id=expected["application_id"],
            flg=flg,
            chain_action=action,
            on_chain=False,
            blockchain_api=api,
            tdr_api=tdr_api,
            diffs=[{
                "field": "certificate_no",
                "tdr": certificate_no,
                "blockchain": "",
                "tdr_field": "certificate_no",
                "tdr_received": certificate_no,
                "tdr_api": tdr_api,
                "blockchain_field": "certificateNumber",
                "blockchain_received": "",
                "blockchain_api": api,
            }],
        )

    actual, chain_sources = drc_parts(unwrap_chain_drc(chain_body, certificate_no))
    diffs = diff_maps(expected, actual, api, tdr_api, tdr_sources, chain_sources)
    if diffs:
        detail = describe_diffs(diffs)
        message = f"DRC fields differ. {detail}" if detail else "DRC fields differ"
        return _result(
            "MISMATCH",
            message,
            application_id=expected["application_id"],
            flg=flg,
            chain_action=action,
            on_chain=True,
            blockchain_api=api,
            tdr_api=tdr_api,
            diffs=diffs,
        )
    return _result("MATCH", "DRC fields match", application_id=expected["application_id"], flg=flg, chain_action=action, on_chain=True)


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
