from __future__ import annotations

import json
import logging
import os
import ssl
import time
import uuid
import urllib.error
import urllib.parse
import urllib.request
from typing import Any

log = logging.getLogger("schedulermp.http")

_SECRET_QUERY = ("key", "token", "password", "secret")

def _ca_candidates() -> list[str]:
    configured = os.environ.get("SSL_CA_FILE", "")
    names = [configured] if configured else []
    names.extend(
        [
            "/etc/pki/tls/certs/ca-bundle.crt",
            "/etc/pki/tls/cert.pem",
            "/etc/ssl/certs/ca-certificates.crt",
            "/etc/ssl/cert.pem",
        ]
    )
    found = []
    for path in names:
        if path and path not in found and os.path.isfile(path):
            found.append(path)
    return found


def _ssl_context() -> ssl.SSLContext:
    context = ssl.create_default_context()
    # Curl on the SDC host trusts the system bundle. Python's default store on
    # that host does not include the same issuer, which fails as CERTIFICATE_VERIFY_FAILED.
    for path in _ca_candidates():
        try:
            context.load_verify_locations(cafile=path)
            log.info("using CA bundle %s", path)
            break
        except ssl.SSLError:
            log.warning("could not load CA bundle %s", path)
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
    code = ""
    if isinstance(body, dict):
        code = str(body.get("code") or "").upper()
    # An existing application is "already exists". An owner registered again on the
    # same application is "already registered" with code DUPLICATE_OWNER. Both are HTTP 400.
    return (
        "already exists" in text
        or "already exist" in text
        or "already registered" in text
        or code == "DUPLICATE_OWNER"
        or status == 409
    )


def safe_url(url: str) -> str:
    parsed = urllib.parse.urlsplit(url)
    query = []
    for key, value in urllib.parse.parse_qsl(parsed.query, keep_blank_values=True):
        if any(word in key.lower() for word in _SECRET_QUERY):
            query.append((key, "***"))
        else:
            query.append((key, value))
    return urllib.parse.urlunsplit((parsed.scheme, parsed.netloc, parsed.path, urllib.parse.urlencode(query), ""))


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
        target = safe_url(url)
        while True:
            started = time.monotonic()
            req = urllib.request.Request(url, data=data, headers=headers, method=method)
            try:
                with urllib.request.urlopen(req, timeout=self.timeout, context=self._ssl) as resp:
                    raw = resp.read().decode("utf-8")
                    elapsed = int((time.monotonic() - started) * 1000)
                    if not raw:
                        log.debug("%s %s %s %s %sms", self.name, method, target, resp.status, elapsed)
                        return resp.status, {}
                    try:
                        parsed = json.loads(raw)
                    except json.JSONDecodeError:
                        log.warning("%s %s %s returned a body that is not JSON", self.name, method, target)
                        raise ApiError(
                            resp.status,
                            f"{self.name} returned a body that is not JSON",
                            {"error": raw[:500]},
                            False,
                        )
                    log.debug("%s %s %s %s %sms", self.name, method, target, resp.status, elapsed)
                    return resp.status, parsed
            except urllib.error.HTTPError as exc:
                raw = exc.read().decode("utf-8", errors="replace")
                try:
                    parsed = json.loads(raw) if raw else {}
                except json.JSONDecodeError:
                    parsed = {"error": raw[:500]}
                retryable = exc.code in {429, 500, 502, 503, 504}
                detail = error_text(parsed) or str(exc.reason)
                expected = is_duplicate(exc.code, parsed) or is_missing(exc.code, parsed)
                if retryable and not expected and attempt < retries:
                    attempt += 1
                    log.info("%s %s %s HTTP %s, retry %s: %s", self.name, method, target, exc.code, attempt, detail)
                    time.sleep(min(2 ** attempt, 8))
                    continue
                if expected:
                    log.debug("%s %s %s HTTP %s: %s", self.name, method, target, exc.code, detail)
                else:
                    log.warning("%s %s %s HTTP %s: %s", self.name, method, target, exc.code, detail)
                raise ApiError(exc.code, f"{self.name} HTTP {exc.code}: {detail}", parsed, retryable) from exc
            except urllib.error.URLError as exc:
                if attempt < retries:
                    attempt += 1
                    log.info("%s %s %s connection failed, retry %s: %s", self.name, method, target, attempt, exc.reason)
                    time.sleep(min(2 ** attempt, 8))
                    continue
                log.warning("%s %s %s connection failed: %s", self.name, method, target, exc.reason)
                raise ApiError(0, f"{self.name} connection failed: {exc.reason}", None, True) from exc
