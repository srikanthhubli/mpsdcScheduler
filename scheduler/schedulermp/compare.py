"""Canonical comparison. Document paths are excluded because TDR returns mixed local and URL paths."""

from __future__ import annotations

from schedulermp.mapping import _text


def norm_num(value) -> str:
    if value is None or value == "":
        return ""
    try:
        number = float(value)
    except (TypeError, ValueError):
        return _text(value)
    rendered = f"{number:.4f}".rstrip("0").rstrip(".")
    return rendered or "0"


def norm_id(value) -> str:
    text = _text(value)
    if text.endswith(".0") and text[:-2].isdigit():
        return text[:-2]
    return text


def drc_canonical(row: dict) -> dict:
    if not isinstance(row, dict):
        row = {}
    certificate = row.get("certificate_no") or row.get("drc_certificate_no") or row.get("certificateNumber")
    application = row.get("applicationid") or row.get("application_id") or row.get("applicationID")
    return {
        "certificate_no": _text(certificate),
        "application_id": _text(application),
        "owner_id": norm_id(row.get("owner_id") or row.get("currentOwnerID")),
        "land_plot_id": norm_id(row.get("land_plot_id")),
        "rid": norm_id(row.get("rid")),
        "flg": _text(row.get("flg") or row.get("drcStage")).upper(),
        "owner_samagra": _text(row.get("owner_samagra") or row.get("samagraID")),
        "owner_from": norm_id(row.get("owner_from")),
        "owner_to": norm_id(row.get("owner_to")),
        "drc_receipt_no": _text(row.get("drc_receipt_no") or row.get("receiptNumber")),
        "drc_file_no": _text(row.get("drc_file_no") or row.get("fileNumber")),
        "actual_value_tdr": norm_num(row.get("actual_value_tdr") if row.get("actual_value_tdr") is not None else row.get("generatedArea")),
        "trn_value_tdr": norm_num(row.get("trn_value_tdr") if row.get("trn_value_tdr") is not None else 0),
        "remaining_value_tdr": norm_num(
            row.get("remaining_value_tdr") if row.get("remaining_value_tdr") is not None else row.get("availableArea")
        ),
    }


def unwrap_chain_drc(body: dict, certificate_no: str) -> dict:
    data = body.get("data") if isinstance(body, dict) else None
    if isinstance(data, list):
        wanted = _text(certificate_no)
        for item in data:
            if isinstance(item, dict) and _text(item.get("certificate_no") or item.get("certificateNumber") or item.get("drcID")) == wanted:
                return item
        return data[0] if data and isinstance(data[0], dict) else {}
    if isinstance(data, dict):
        return data
    return body if isinstance(body, dict) else {}


def diff_maps(expected: dict, actual: dict) -> list[dict]:
    diffs = []
    for key, left in expected.items():
        right = actual.get(key, "")
        if left != right:
            diffs.append({"field": key, "tdr": left, "blockchain": right})
    return diffs


def generating_canonical(body: dict) -> dict:
    return {
        "application_id": _text(body.get("p_application_id") or body.get("applicationid") or body.get("application_id")),
        "project_name": _text(body.get("p_project_name") or body.get("project_name")),
        "agency_name": _text(body.get("p_implementation_agency") or body.get("agency_name") or body.get("implementation_agency")),
    }


def chain_application_canonical(body: dict) -> dict:
    data = body.get("data") if isinstance(body, dict) else {}
    if not isinstance(data, dict):
        data = {}
    return {
        "application_id": _text(data.get("applicationid") or data.get("applicationID")),
        "project_name": _text(data.get("project_name")),
        "agency_name": _text(data.get("agency_name")),
    }


def owner_canonical(body: dict, application_id: str = "") -> dict:
    return {
        "application_id": _text(body.get("applicationid") or body.get("application_id") or application_id),
        "owner_id": norm_id(body.get("owner_id")),
        "name": _text(body.get("ownernm") or body.get("name") or body.get("owner_name")),
        "samagra": _text(body.get("owner_samagra") or body.get("samagraID")),
        "mobile": _text(body.get("owner_mob") or body.get("mobile")),
    }


def chain_owner_canonical(body: dict) -> dict:
    data = body.get("data") if isinstance(body, dict) else {}
    if not isinstance(data, dict):
        data = {}
    owner = data.get("owner") if isinstance(data.get("owner"), dict) else data
    application = (
        data.get("applicationid")
        or data.get("applicationID")
        or owner.get("applicationid")
        or owner.get("applicationID")
    )
    return owner_canonical(
        {
            "applicationid": application,
            "owner_id": owner.get("owner_id") or owner.get("ownerID") or data.get("owner_id") or data.get("ownerID"),
            "ownernm": owner.get("name") or owner.get("ownernm") or owner.get("owner_name"),
            "owner_samagra": owner.get("samagraID") or owner.get("owner_samagra"),
            "owner_mob": owner.get("mobile") or owner.get("owner_mob"),
        }
    )
