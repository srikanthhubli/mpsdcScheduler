from __future__ import annotations

import urllib.parse
import logging

from schedulermp.config import Settings
from schedulermp.http_client import ApiError, HttpClient, error_text, is_duplicate, is_missing

log = logging.getLogger("schedulermp.chain")


class ChainClient:
    """MP-TDR legacy blockchain APIs. Writes are the four business endpoints."""

    def __init__(self, settings: Settings):
        headers = {}
        if settings.blockchain_api_key:
            headers["X-API-Key"] = settings.blockchain_api_key
        self.http = HttpClient(settings.blockchain_base_url, settings.http_timeout_sec, headers, name="Blockchain")
        self.settings = settings
        self.dry_run = settings.dry_run

    def _target(self) -> dict:
        return {
            "channel": self.settings.channel,
            "org": self.settings.org,
            "peer": self.settings.peer,
        }

    def get_drc(self, certificate_no: str) -> tuple[int, dict]:
        """Legacy GetDRCDetails keeps owner_from and owner_to. The v1.4 read omits them."""
        status, body = self.get("/Agency/GetDRCDetails", {"certificateNumber": certificate_no})
        if status < 400 and not is_missing(status, body):
            return status, body
        encoded = urllib.parse.quote(certificate_no, safe="/")
        return self.get(f"/api/tdr/drcs/{encoded}", {})

    def get_owner(self, owner_id: str, application_id: str) -> tuple[int, dict]:
        """GET /api/tdr/owners/{ownerId}, then legacy GetOwnerDetails."""
        encoded = urllib.parse.quote(str(owner_id), safe="")
        status, body = self.get(f"/api/tdr/owners/{encoded}", {})
        if status < 400 and not is_missing(status, body):
            return status, body
        return self.get(
            "/Agency/GetOwnerDetails",
            {"owner_id": owner_id, "applicationid": application_id},
        )

    def get(self, path: str, params: dict | None = None) -> tuple[int, dict]:
        query = {**(params or {}), **self._target()}
        try:
            status, body = self.http.request("GET", path, query, retries=2)
            return status, body if isinstance(body, dict) else {"data": body}
        except ApiError as exc:
            if is_missing(exc.status, exc.body):
                return exc.status or 404, exc.body if isinstance(exc.body, dict) else {"error": exc.message}
            raise

    def post(self, path: str, body: dict) -> dict:
        payload = {
            **body,
            "changeMeta": {
                "changedBy": self.settings.changed_by,
                "changedByName": "TDR Scheduler",
                "changedByRole": "INTEGRATION",
                "deviceType": "server",
                "deviceName": "schedulerMP",
                "appVersion": "1.0.0",
                "remarks": "TDR phase sync",
            },
        }
        if self.dry_run:
            return {"dry_run": True, "path": path, "transactionId": "dry-run"}
        try:
            _status, response = self.http.request("POST", path, self._target(), payload, retries=1)
            return response if isinstance(response, dict) else {"data": response}
        except ApiError as exc:
            if is_duplicate(exc.status, exc.body):
                stored = exc.body if isinstance(exc.body, dict) else {}
                log.info("blockchain %s already stored: %s", path, error_text(exc.body))
                return {**stored, "duplicate": True, "error": error_text(exc.body)}
            raise


def tx_id(response: dict | None) -> str:
    if not isinstance(response, dict):
        return ""
    for key in ("transactionId", "txId", "blockchain_tx_id", "blockchainTxID"):
        value = response.get(key)
        if isinstance(value, str) and value:
            return value
    data = response.get("data")
    if isinstance(data, dict):
        return tx_id(data)
    return ""
