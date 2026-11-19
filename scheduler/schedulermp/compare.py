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


def _show(value) -> str:
    if value is None:
        return ""
    return _text(value)


def _pick(row: dict, keys: tuple[str, ...], normalize, default=None) -> tuple[str, str, str]:
    source = row if isinstance(row, dict) else {}
    for key in keys:
        if key not in source or source.get(key) is None or source.get(key) == "":
            continue
        raw = source.get(key)
        return normalize(raw), key, _show(raw)
    if default is not None:
        return normalize(default), "", ""
    return normalize(None), "", ""


def _parts(row: dict, spec: list[tuple]) -> tuple[dict, dict]:
    values = {}
    sources = {}
    for field, keys, normalize, default in spec:
        value, name, received = _pick(row, keys, normalize, default)
        values[field] = value
        sources[field] = {"field": name, "received": received}
    return values, sources


def _drc_spec() -> list[tuple]:
    return [
        ("certificate_no", ("certificate_no", "drc_certificate_no", "certificateNumber"), _text, None),
        ("application_id", ("applicationid", "application_id", "applicationID"), _text, None),
        ("owner_id", ("owner_id", "currentOwnerID"), norm_id, None),
        ("land_plot_id", ("land_plot_id",), norm_id, None),
        ("rid", ("rid",), norm_id, None),
        ("flg", ("flg", "drcStage"), lambda value: _text(value).upper(), None),
        ("owner_samagra", ("owner_samagra", "samagraID"), _text, None),
        ("owner_from", ("owner_from",), norm_id, None),
        ("owner_to", ("owner_to",), norm_id, None),
        ("drc_receipt_no", ("drc_receipt_no", "receiptNumber"), _text, None),
        ("drc_file_no", ("drc_file_no", "fileNumber"), _text, None),
        ("actual_value_tdr", ("actual_value_tdr", "generatedArea"), norm_num, None),
        ("trn_value_tdr", ("trn_value_tdr",), norm_num, 0),
        ("remaining_value_tdr", ("remaining_value_tdr", "availableArea"), norm_num, None),
    ]


def drc_parts(row: dict) -> tuple[dict, dict]:
    return _parts(row if isinstance(row, dict) else {}, _drc_spec())


def drc_canonical(row: dict) -> dict:
    values, _sources = drc_parts(row)
    return values


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


def diff_maps(
    expected: dict,
    actual: dict,
    blockchain_api: str = "",
    tdr_api: str = "",
    tdr_sources: dict | None = None,
    chain_sources: dict | None = None,
) -> list[dict]:
    diffs = []
    tdr_sources = tdr_sources or {}
    chain_sources = chain_sources or {}
    for key, left in expected.items():
        right = actual.get(key, "")
        if left != right:
            tdr_source = tdr_sources.get(key) or {}
            chain_source = chain_sources.get(key) or {}
            diffs.append(
                {
                    "field": key,
                    "tdr": left,
                    "blockchain": right,
                    "tdr_field": tdr_source.get("field") or key,
                    "tdr_received": tdr_source.get("received", left),
                    "tdr_api": tdr_api,
                    "blockchain_field": chain_source.get("field") or key,
                    "blockchain_received": chain_source.get("received", right),
                    "blockchain_api": blockchain_api,
                }
            )
    return diffs


def describe_diffs(diffs: list[dict], limit: int = 6) -> str:
    parts = []
    for item in diffs[:limit]:
        if "tdr_received" in item:
            tdr = item.get("tdr_received") or "blank"
        else:
            tdr = item.get("tdr") or "blank"
        if "blockchain_received" in item:
            chain = item.get("blockchain_received") or "blank"
        else:
            chain = item.get("blockchain") or "blank"
        tdr_field = item.get("tdr_field") or ""
        chain_field = item.get("blockchain_field") or ""
        tdr_bit = f"{tdr_field}={tdr}" if tdr_field else str(tdr)
        chain_bit = f"{chain_field}={chain}" if chain_field else str(chain)
        text = f"{item.get('field')} (TDR: {tdr_bit}, blockchain: {chain_bit}"
        if item.get("tdr_api"):
            text += f", TDR API: {item.get('tdr_api')}"
        if item.get("blockchain_api"):
            text += f", blockchain API: {item.get('blockchain_api')}"
        parts.append(text + ")")
    if len(diffs) > limit:
        parts.append(f"{len(diffs) - limit} more field(s)")
    return "; ".join(parts)


def _generating_spec() -> list[tuple]:
    return [
        ("application_id", ("p_application_id", "applicationid", "application_id"), _text, None),
        ("project_name", ("p_project_name", "project_name"), _text, None),
        ("agency_name", ("p_implementation_agency", "agency_name", "implementation_agency"), _text, None),
    ]


def generating_parts(body: dict) -> tuple[dict, dict]:
    return _parts(body if isinstance(body, dict) else {}, _generating_spec())


def generating_canonical(body: dict) -> dict:
    values, _sources = generating_parts(body)
    return values


def chain_application_parts(body: dict) -> tuple[dict, dict]:
    data = body.get("data") if isinstance(body, dict) else {}
    if not isinstance(data, dict):
        data = {}
    return _parts(data, [
        ("application_id", ("applicationid", "applicationID", "p_application_id"), _text, None),
        ("project_name", ("project_name", "p_project_name"), _text, None),
        ("agency_name", ("agency_name", "p_implementation_agency", "implementation_agency"), _text, None),
    ])


def chain_application_canonical(body: dict) -> dict:
    values, _sources = chain_application_parts(body)
    return values


def _owner_spec() -> list[tuple]:
    return [
        ("application_id", ("applicationid", "application_id"), _text, None),
        ("owner_id", ("owner_id", "ownerID"), norm_id, None),
        ("name", ("ownernm", "name", "owner_name"), _text, None),
        ("samagra", ("owner_samagra", "samagraID"), _text, None),
        ("mobile", ("owner_mob", "mobile"), _text, None),
    ]


def owner_parts(body: dict, application_id: str = "") -> tuple[dict, dict]:
    row = dict(body) if isinstance(body, dict) else {}
    if application_id and not row.get("applicationid") and not row.get("application_id"):
        row["application_id"] = application_id
    return _parts(row, _owner_spec())


def owner_canonical(body: dict, application_id: str = "") -> dict:
    values, _sources = owner_parts(body, application_id)
    return values


def chain_owner_row(body: dict) -> dict:
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
    return {
        "applicationid": application,
        "owner_id": owner.get("owner_id") or owner.get("ownerID") or data.get("owner_id") or data.get("ownerID"),
        "ownernm": owner.get("name") or owner.get("ownernm") or owner.get("owner_name"),
        "owner_samagra": owner.get("samagraID") if "samagraID" in owner else owner.get("owner_samagra"),
        "owner_mob": owner.get("mobile") if "mobile" in owner else owner.get("owner_mob"),
    }


def chain_owner_parts(body: dict) -> tuple[dict, dict]:
    data = body.get("data") if isinstance(body, dict) else {}
    if not isinstance(data, dict):
        data = {}
    owner = data.get("owner") if isinstance(data.get("owner"), dict) else data
    values, sources = owner_parts(chain_owner_row(body))
    renamed = {
        "application_id": ("applicationid", "applicationID"),
        "owner_id": ("owner_id", "ownerID"),
        "name": ("name", "ownernm", "owner_name"),
        "samagra": ("samagraID", "owner_samagra"),
        "mobile": ("mobile", "owner_mob"),
    }
    for field, keys in renamed.items():
        _value, name, received = _pick(owner, keys, _text if field not in {"owner_id"} else norm_id)
        if field == "application_id":
            _value, name, received = _pick(data, keys, _text)
            if not name:
                _value, name, received = _pick(owner, keys, _text)
        sources[field] = {"field": name or keys[0], "received": received}
    return values, sources


def chain_owner_canonical(body: dict) -> dict:
    values, _sources = chain_owner_parts(body)
    return values
