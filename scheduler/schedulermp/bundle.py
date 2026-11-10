"""Fold the phase TDR responses into one application bundle."""

from __future__ import annotations

from dataclasses import dataclass, field

from schedulermp.mapping import _text, is_plot_row, lists_from_payload, pick_generating, to_land, to_plot


def _rows(value) -> list[dict]:
    if isinstance(value, list):
        return [item for item in value if isinstance(item, dict)]
    if isinstance(value, dict):
        return [value]
    return []


def _dedupe(rows: list[dict], key_fn) -> list[dict]:
    seen = set()
    out = []
    for row in rows:
        key = key_fn(row)
        if key and key in seen:
            continue
        if key:
            seen.add(key)
        out.append(row)
    return out


@dataclass
class Bundle:
    application_id: str
    generating: dict = field(default_factory=dict)
    plots: list = field(default_factory=list)
    lands: list = field(default_factory=list)
    owners: list = field(default_factory=list)
    docs: list = field(default_factory=list)
    multi_owners: list = field(default_factory=list)
    drcs: list = field(default_factory=list)
    transfers: list = field(default_factory=list)

    def absorb(self, payload: dict) -> None:
        if not isinstance(payload, dict):
            return
        generating_rows = lists_from_payload(
            payload, ("generatingarea", "generating_area", "project_details")
        )
        chosen = pick_generating(generating_rows)
        if chosen and (
            not self.generating or (chosen.get("p_application_id") and not self.generating.get("p_application_id"))
        ):
            self.generating = chosen
        for row in lists_from_payload(payload, ("plotRecords", "landplotRecords", "land_or_plot_details")):
            if is_plot_row(row):
                self.plots.append(to_plot(row))
            else:
                self.lands.append(to_land(row))
        for row in lists_from_payload(payload, ("landRecords",)):
            if is_plot_row(row) and not (row.get("p_khasra_no") or row.get("land_id")):
                self.plots.append(to_plot(row))
            else:
                self.lands.append(to_land(row))
        self.owners.extend(lists_from_payload(payload, ("owners", "owner", "owner_details")))
        self.docs.extend(lists_from_payload(payload, ("ownerDocs", "ownerDoc", "owner_documents")))
        self.multi_owners.extend(lists_from_payload(payload, ("multiOwner", "multi_owner")))
        self.drcs.extend(lists_from_payload(payload, ("drc_upload", "certificate_details", "drcs")))
        self.transfers.extend(
            lists_from_payload(payload, ("transfer", "transfers", "transfer_history"))
        )
        self._nested_from_owners()
        self._compact()

    def _nested_from_owners(self) -> None:
        """Application detail keeps drc_upload, transfer, and ownerDocs inside each owner."""
        for owner in self.owners:
            for key in ("drc_upload", "certificate_details", "drcs"):
                self.drcs.extend(_rows(owner.get(key)))
            for key in ("transfer", "transfers", "transfer_history"):
                self.transfers.extend(_rows(owner.get(key)))
            for key in ("ownerDocs", "ownerDoc", "owner_documents"):
                self.docs.extend(_rows(owner.get(key)))
            for key in ("multiOwner", "multi_owner"):
                self.multi_owners.extend(_rows(owner.get(key)))

    def _compact(self) -> None:
        self.plots = _dedupe(self.plots, lambda row: _text(row.get("plot_id") or row.get("plot_no")))
        self.lands = _dedupe(self.lands, lambda row: _text(row.get("land_id") or row.get("p_khasra_no") or row.get("p_kid")))
        self.owners = _dedupe(self.owners, lambda row: _text(row.get("owner_id")))
        self.docs = _dedupe(self.docs, lambda row: _text(row.get("owner_id")) + "|" + _text(row.get("doc_type")) + "|" + _text(row.get("doc_path")))
        self.drcs = _dedupe(
            self.drcs,
            lambda row: _text(row.get("certificate_no") or row.get("drc_certificate_no") or row.get("certificateNumber")),
        )
        self.transfers = _dedupe(self.transfers, lambda row: _text(row.get("transfer_id") or row.get("transferID") or id(row)))

    def resolved_application_id(self) -> str:
        if self.application_id:
            return self.application_id
        for source in (
            self.generating.get("p_application_id"),
            self.generating.get("application_id"),
        ):
            if source:
                return _text(source)
        return ""
