from schedulermp.config import Settings
from schedulermp.http_client import HttpClient


class TdrClient:
    """TDR DataSharing reads from the phase 1/2/3 Postman collection."""

    def __init__(self, settings: Settings):
        headers = {}
        if settings.tdr_api_key:
            value = settings.tdr_api_key
            if settings.tdr_auth_header.lower() == "authorization" and not value.lower().startswith("bearer "):
                value = f"Bearer {value}"
            headers[settings.tdr_auth_header] = value
        self.http = HttpClient(settings.tdr_base_url, settings.http_timeout_sec, headers, name="TDR")

    def certificate_numbers(self) -> list[str]:
        _status, body = self.http.request("GET", "/GetDRCNoList")
        rows = body.get("certificate_numbers") or []
        numbers = []
        for row in rows:
            if isinstance(row, dict) and row.get("certificate_number"):
                numbers.append(str(row["certificate_number"]))
            elif isinstance(row, str):
                numbers.append(row)
        return numbers

    def drc_by_certificate(self, certificate_no: str) -> dict:
        _status, body = self.http.request(
            "GET",
            "/GetDetailByCertificateNo",
            {"certificateNo": certificate_no},
        )
        return body

    def application_list(self) -> list[dict]:
        _status, body = self.http.request("GET", "/GetApplicationList")
        data = body.get("data") or []
        return [row for row in data if isinstance(row, dict)]

    def application_detail(self, application_id: str) -> dict:
        _status, body = self.http.request(
            "GET",
            "/GetApplicationDetailByApplicationID",
            {"application_id": application_id},
        )
        return body

    def owner_by_id(self, owner_id: str) -> dict:
        _status, body = self.http.request(
            "GET",
            "/getOwnerDetailByOwnerID",
            {"owner_id": owner_id},
        )
        return body

    def generating_by_application(self, application_id: str) -> dict:
        _status, body = self.http.request(
            "GET",
            "/GetGeneratingApplicationByApplicationID",
            {"applicationid": application_id},
        )
        return body

    def owner_by_certificate(self, certificate_no: str) -> dict:
        _status, body = self.http.request(
            "GET",
            "/getOwnerDetailByCertificateNo",
            {"certificateno": certificate_no},
        )
        return body
