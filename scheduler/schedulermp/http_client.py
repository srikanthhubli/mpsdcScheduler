import json
import ssl
import time
import uuid
import urllib.error
import urllib.parse
import urllib.request
from typing import Any

def _ssl_context() -> ssl.SSLContext:
    context = ssl.create_default_context()
    # mpbsp-uat.mp.gov.in negotiates legacy TLS renegotiation. OpenSSL 3 rejects it
    # unless this option is set, which surfaces as a browser "Failed to fetch".
    legacy = getattr(ssl, "OP_LEGACY_SERVER_CONNECT", 0)
    if legacy:
        context.options |= legacy
    return context


class ApiError(Exception):
    def __init__(self, status: int, message: str, body: Any = None, retryable: bool = False):
        super().__init__(message)
        self.status = status
        self.message = message
        self.body = body
        self.retryable = retryable


def error_text(body: Any) -> str:
    if isinstance(body, dict):
        for key in ("error", "message", "error_code"):
            value = body.get(key)
            if isinstance(value, str) and value:
                return value
        return json.dumps(body, ensure_ascii=False)[:500]
    if body is None:
        return ""
    return str(body)[:500]


def is_missing(status: int, body: Any) -> bool:
    text = error_text(body).lower()
    if status == 404:
        return True
    return "not found" in text or "does not exist" in text or "record_not_found" in text


def is_duplicate(status: int, body: Any) -> bool:
    text = error_text(body).lower()
    # Fabric reports an existing record as HTTP 400 with "already exists", not 409.
    return "already exists" in text or "already exist" in text or status == 409


class HttpClient:
    def __init__(self, base_url: str, timeout: int, headers: dict[str, str] | None = None, name: str = "API"):
        self.base_url = base_url.rstrip("/")
        self.timeout = timeout
        self.headers = headers or {}
        self.name = name
        self._ssl = _ssl_context()

    def request(
        self,
        method: str,
        path: str,
        params: dict | None = None,
        body: dict | None = None,
        extra_headers: dict | None = None,
        retries: int = 2,
    ) -> tuple[int, Any]:
        url = self.base_url + path
        if params:
            clean = {k: v for k, v in params.items() if v is not None and v != ""}
            if clean:
                url = url + "?" + urllib.parse.urlencode(clean, doseq=True)
        data = None
        headers = {"Accept": "application/json", "X-Request-ID": str(uuid.uuid4()), **self.headers}
        if extra_headers:
            headers.update(extra_headers)
        if body is not None:
            data = json.dumps(body).encode("utf-8")
            headers["Content-Type"] = "application/json"
        attempt = 0
        while True:
            req = urllib.request.Request(url, data=data, headers=headers, method=method)
            try:
                with urllib.request.urlopen(req, timeout=self.timeout, context=self._ssl) as resp:
                    raw = resp.read().decode("utf-8")
                    if not raw:
                        return resp.status, {}
                    try:
                        parsed = json.loads(raw)
                    except json.JSONDecodeError:
                        raise ApiError(
                            resp.status,
                            f"{self.name} returned a body that is not JSON",
                            {"error": raw[:500]},
                            False,
                        )
                    return resp.status, parsed
            except urllib.error.HTTPError as exc:
                raw = exc.read().decode("utf-8", errors="replace")
                try:
                    parsed = json.loads(raw) if raw else {}
                except json.JSONDecodeError:
                    parsed = {"error": raw[:500]}
                retryable = exc.code in {429, 500, 502, 503, 504}
                if retryable and attempt < retries:
                    attempt += 1
                    time.sleep(min(2 ** attempt, 8))
                    continue
                detail = error_text(parsed) or str(exc.reason)
                raise ApiError(exc.code, f"{self.name} HTTP {exc.code}: {detail}", parsed, retryable) from exc
            except urllib.error.URLError as exc:
                if attempt < retries:
                    attempt += 1
                    time.sleep(min(2 ** attempt, 8))
                    continue
                raise ApiError(0, f"{self.name} connection failed: {exc.reason}", None, True) from exc
