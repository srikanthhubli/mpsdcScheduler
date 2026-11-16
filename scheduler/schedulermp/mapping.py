"""Map live TDR DataSharing payloads onto the four blockchain write bodies."""

from __future__ import annotations

P_FROM_PROJECT = {
    "application_id": "p_application_id",
    "rid": "p_rid",
    "implementation_agency": "p_implementation_agency",
    "project_name": "p_project_name",
    "dist_name_e": "p_district",
    "district": "p_district",
    "town_name_e": "p_town_city",
    "town_city": "p_town_city",
    "proposed_for": "p_proposed_for",
    "stage": "p_stage",
    "officer_name": "p_officer_name",
    "designation": "p_designation",
    "email": "p_email",
    "mob_no": "p_mob_no",
    "id": "p_id",
    "userid": "p_userid",
    "assesment_value": "p_assesment_value",
    "affected_plots": "p_affected_plots",
    "site_plan_doc": "p_site_plan_doc",
    "site_plan_doc_name": "p_site_plan_doc_name",
    "area_map_doc": "p_area_map_doc",
    "area_map_doc_name": "p_area_map_doc_name",
    "transferto": "p_transferto",
    "currentststus": "p_currentststus",
    "submit_status": "p_submit_status",
    "roleid": "p_roleid",
    "insertedby_ipddress": "p_insertedby_ipddress",
    "tehsil_cd": "p_tehsil_cd",
    "vill_cd": "p_vill_cd",
    "notification_no": "p_notification_no",
    "project_doc": "p_project_doc",
    "project_doc_name": "p_project_doc_name",
    "planning_area": "p_planning_area",
    "project_location": "p_project_location",
    "updatedby_remarks": "p_updatedby_remarks",
    "project_khasra_village": "p_project_khasra_village",
    "project_khasra_no": "p_project_khasra_no",
    "project_khasra_area": "p_project_khasra_area",
    "project_khasra_proposed_area": "p_project_khasra_proposed_area",
}

OWNER_FIELDS = [
    "owner_id",
    "land_plot_id",
    "rid",
    "owner_type",
    "ownernm",
    "owner_father_spouse_nm",
    "owner_dob",
    "owner_gender",
    "owner_city",
    "owner_pin",
    "owner_samagra",
    "owner_mob",
    "owner_email",
    "owner_photo_name",
    "owner_photo_path",
    "owner_form3_name",
    "owner_form3_path",
    "owner_mutation_name",
    "owner_mutation_path",
    "owner_ekyc",
    "owner_address",
    "owner_addressproof_doc_name",
    "owner_addressproof_doc_path",
    "owner_consent",
    "drc_receipt_no",
    "receipt_dt",
    "is_multi_owner",
]

DRC_FLAGS = {"FIRST_OWNER", "TRANSFER_OWNER", "TRANSFEREE_OWNER", "UTILIZATION_OWNER"}
DRC_UPDATE_FLAGS = {"TRANSFER_OWNER", "UTILIZATION_OWNER"}
DRC_GENERATE_FLAGS = {"FIRST_OWNER", "TRANSFEREE_OWNER"}


def _text(value) -> str:
    if value is None:
        return ""
    return str(value).strip()


def lists_from_payload(payload: dict, keys: tuple[str, ...]) -> list[dict]:
    if not isinstance(payload, dict):
        return []
    roots: list[dict] = [payload]
    data = payload.get("data")
    if isinstance(data, dict):
        roots.append(data)
    elif isinstance(data, list):
        roots.extend(item for item in data if isinstance(item, dict))
    found: list[dict] = []
    for root in roots:
        for key in keys:
            value = root.get(key)
            if isinstance(value, list):
                found.extend(item for item in value if isinstance(item, dict))
            elif isinstance(value, dict):
                found.append(value)
    return found


def pick_generating(rows: list[dict]) -> dict:
    preferred = [row for row in rows if row.get("p_application_id") or row.get("p_project_name")]
    use = preferred or rows
    if not use:
        return {}
    base = dict(use[0])
    locations = []
    for row in use:
        loc = row.get("p_project_location") or row.get("project_location")
        if loc and loc not in locations:
            locations.append(loc)
    if len(locations) > 1:
        if "p_project_location" in base or any(row.get("p_application_id") for row in use):
            base["p_project_location"] = " | ".join(str(item) for item in locations)
        else:
            base["project_location"] = " | ".join(str(item) for item in locations)
    return base


def to_plot(row: dict) -> dict:
    plot_id = _text(row.get("plot_id") or row.get("plot_no"))
    return {
        "teh_cd": row.get("teh_cd") or "",
        "vill_cd": row.get("vill_cd") or "",
        "colony_name": row.get("colony_name") or "",
        "registry_no": row.get("registry_no") or "",
        "plot_no": row.get("plot_no") or "",
        "registry_area": row.get("registry_area") if row.get("registry_area") is not None else 0,
        "proposed_area": row.get("proposed_area") if row.get("proposed_area") is not None else 0,
        "ownership": row.get("ownership") or "",
        "value_tdr": row.get("value_tdr") if row.get("value_tdr") is not None else 0,
        "land_use": row.get("land_use") or "",
        "remark": row.get("remark") or "",
        "rid": row.get("rid"),
        "registry_sampada": row.get("registry_sampada") or "",
        "lat": _text(row.get("lat")),
        "lang": _text(row.get("lang")),
        "plot_id": plot_id,
    }


def to_land(row: dict) -> dict:
    if row.get("p_khasra_no") or row.get("land_id") or row.get("p_area"):
        land = dict(row)
        land.setdefault("land_id", _text(row.get("land_id") or row.get("p_kid") or row.get("p_khasra_no")))
        return land
    return {
        "p_teh_cd": row.get("teh_cd") or "",
        "p_vill_cd": row.get("vill_cd") or "",
        "p_kid": _text(row.get("plot_id") or row.get("khasra_no")),
        "p_area": row.get("registry_area") or 0,
        "p_owner_name": row.get("ownership") or "",
        "p_area_proposed": row.get("proposed_area") or 0,
        "p_value_tdr": row.get("value_tdr") or 0,
        "p_landuse": row.get("land_use") or "",
        "p_remark": row.get("remark") or "",
        "p_rid": row.get("rid"),
        "p_khasra_no": row.get("plot_no") or row.get("khasra_no") or "",
        "p_address": row.get("colony_name") or "",
        "p_plot_no": row.get("plot_no") or "",
        "land_id": _text(row.get("plot_id") or row.get("land_id") or row.get("plot_no")),
        "lat": _text(row.get("lat")),
        "lang": _text(row.get("lang")),
    }


def is_plot_row(row: dict) -> bool:
    if row.get("p_khasra_no") and not row.get("plot_no"):
        return False
    return bool(row.get("plot_no") or row.get("plot_id") or row.get("colony_name"))


def generating_body(source: dict, plots: list[dict], lands: list[dict]) -> dict:
    if source.get("p_application_id") or source.get("p_project_name"):
        body = {key: value for key, value in source.items() if key.startswith("p_")}
    else:
        body = {}
        for src, dest in P_FROM_PROJECT.items():
            if src in source:
                body[dest] = source[src]
    body.setdefault("p_insertedby_ipddress", source.get("insertedby_ipddress") or source.get("p_insertedby_ipddress") or "")
    body.setdefault("p_transferto", source.get("p_transferto") if source.get("p_transferto") is not None else 0)
    body["landRecords"] = [to_land(row) for row in lands]
    body["plotRecords"] = [to_plot(row) for row in plots]
    return body


def owner_body(owner: dict, application_id: str, docs: list[dict], multi: list[dict] | None = None) -> dict:
    body = {key: owner.get(key) for key in OWNER_FIELDS}
    body["applicationid"] = _text(owner.get("applicationid") or owner.get("application_id") or application_id)
    owner_type = _text(owner.get("owner_type") or "PLOT").upper()
    body["owner_type"] = owner_type if owner_type in {"LAND", "PLOT"} else "PLOT"
    body["owner_id"] = owner.get("owner_id")
    body["land_plot_id"] = _text(owner.get("land_plot_id"))
    body["rid"] = owner.get("rid")
    owner_docs = []
    for doc in docs:
        if _text(doc.get("owner_id")) in {"", _text(owner.get("owner_id"))}:
            owner_docs.append(
                {
                    "owner_id": _text(doc.get("owner_id") or owner.get("owner_id")),
                    "doc_type": doc.get("doc_type") or "",
                    "doc_path": doc.get("doc_path") or "",
                }
            )
    body["ownerDocs"] = owner_docs
    body["multiOwner"] = multi or owner.get("multiOwner") or owner.get("multi_owner") or []
    if not isinstance(body["multiOwner"], list):
        body["multiOwner"] = []
    return body


def drc_body(row: dict, application_id: str = "") -> dict:
    certificate = _text(row.get("certificate_no") or row.get("drc_certificate_no") or row.get("certificateNumber"))
    flg = _text(row.get("flg") or "FIRST_OWNER").upper()
    return {
        "applicationid": _text(row.get("applicationid") or row.get("application_id") or application_id),
        "owner_id": row.get("owner_id"),
        "land_plot_id": _text(row.get("land_plot_id")),
        "rid": row.get("rid"),
        "drc_certificate_doc_name": row.get("drc_certificate_doc_name") or "",
        "drc_certificate_doc_path": row.get("drc_certificate_doc_path") or "",
        "drc_receipt_no": _text(row.get("drc_receipt_no")),
        "drc_file_no": _text(row.get("drc_file_no")),
        "flg": flg,
        "owner_samagra": _text(row.get("owner_samagra")),
        "certificate_no": certificate,
        "owner_from": _text(row.get("owner_from")),
        "owner_to": _text(row.get("owner_to")),
        "actual_value_tdr": row.get("actual_value_tdr"),
        "trn_value_tdr": row.get("trn_value_tdr") if row.get("trn_value_tdr") is not None else 0,
        "remaining_value_tdr": row.get("remaining_value_tdr"),
    }


def transfer_body(row: dict, application_id: str, certificate_no: str, transferor_owner_id) -> dict | None:
    if isinstance(row.get("param_array"), list) and row["param_array"]:
        body = dict(row)
        body["querytype"] = row.get("querytype") or "TRANSFER"
        body["applicationid"] = _text(row.get("applicationid") or application_id)
        body["certificate_no"] = _text(row.get("certificate_no") or certificate_no)
        body["transferor_owner_id"] = row.get("transferor_owner_id") or transferor_owner_id
        body.setdefault("param_array_doc", row.get("param_array_doc") or [])
        return body
    transferee_id = row.get("to_owner_id") or row.get("owner_to") or row.get("transferee_owner_id")
    name = row.get("owner_name") or row.get("ownernm") or row.get("transferee_name")
    if not transferee_id or not name:
        return None
    if _text(transferee_id) == _text(transferor_owner_id):
        return None
    return {
        "querytype": "TRANSFER",
        "applicationid": _text(row.get("applicationid") or row.get("application_id") or application_id),
        "certificate_no": _text(row.get("certificate_no") or row.get("drc_certificate_no") or certificate_no),
        "transferor_owner_id": row.get("transferor_owner_id") or row.get("owner_from") or transferor_owner_id,
        "transfer_id": _text(row.get("transfer_id") or row.get("transferID")),
        "param_array": [
            {
                "owner_id": transferee_id,
                "owner_name": name,
                "owner_mob": _text(row.get("owner_mob")),
                "owner_email": _text(row.get("owner_email")),
                "trn_value_tdr": _text(row.get("trn_value_tdr") or row.get("transferArea") or "0"),
                "trn_date": _text(row.get("trn_date") or row.get("transferDate")),
                "trn_time": _text(row.get("trn_time")),
                "ip": _text(row.get("ip")),
                "owner_address": _text(row.get("owner_address")),
                "owner_dob": _text(row.get("owner_dob")),
                "owner_gender": _text(row.get("owner_gender")),
                "owner_city": _text(row.get("owner_city")),
                "owner_pin": _text(row.get("owner_pin")),
                "samagra_no": _text(row.get("samagra_no") or row.get("owner_samagra")),
            }
        ],
        "param_array_doc": row.get("param_array_doc") or row.get("transfer_documents") or [],
    }


def valid_flg(flg: str) -> bool:
    return flg in DRC_FLAGS


def chain_action(flg: str) -> str:
    """MPSDC DRCUpload mode. Update flags change an existing ledger DRC. Generate flags create one."""
    value = _text(flg).upper()
    if value in DRC_UPDATE_FLAGS:
        return "update"
    if value in DRC_GENERATE_FLAGS:
        return "generate"
    return ""
