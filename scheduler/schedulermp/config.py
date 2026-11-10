import os
from dataclasses import dataclass


def _bool(name: str, default: bool) -> bool:
    raw = os.environ.get(name)
    if raw is None or raw == "":
        return default
    return raw.strip().lower() in {"1", "true", "yes", "y", "on"}


def _int(name: str, default: int) -> int:
    raw = os.environ.get(name)
    if raw is None or raw == "":
        return default
    return int(raw)


@dataclass(frozen=True)
class Settings:
    tdr_base_url: str
    tdr_api_key: str
    tdr_auth_header: str
    blockchain_base_url: str
    blockchain_api_key: str
    channel: str
    org: str
    peer: str
    callback_url: str
    state_path: str
    http_host: str
    http_port: int
    scheduler_api_key: str
    admin_username: str
    admin_password: str
    phase1_enabled: bool
    phase1_interval_sec: int
    phase1_concurrency: int
    phase2_enabled: bool
    phase2_interval_sec: int
    phase2_scan_certs: bool
    phase3_enabled: bool
    phase3_interval_sec: int
    phase3_scan_certs: bool
    dry_run: bool
    http_timeout_sec: int
    max_retries: int
    changed_by: str


def load_settings() -> Settings:
    return Settings(
        tdr_base_url=os.environ.get(
            "TDR_BASE_URL",
            "https://gisdemo.mp.gov.in/TDR/TDRService/api/DataSharing",
        ).rstrip("/"),
        tdr_api_key=os.environ.get("TDR_API_KEY", ""),
        tdr_auth_header=os.environ.get("TDR_AUTH_HEADER", "Authorization"),
        blockchain_base_url=os.environ.get(
            "BLOCKCHAIN_BASE_URL", "https://mpbsp-uat.mp.gov.in"
        ).rstrip("/"),
        blockchain_api_key=os.environ.get("BLOCKCHAIN_API_KEY", ""),
        channel=os.environ.get("CHANNEL", "mptdr"),
        org=os.environ.get("ORG", "mpgovdepartment"),
        peer=os.environ.get("PEER", "peer0-mpgovdepartment"),
        callback_url=os.environ.get("TDR_CALLBACK_URL", "").rstrip("/"),
        state_path=os.environ.get("STATE_PATH", "./data/state.json"),
        http_host=os.environ.get("HTTP_HOST", "0.0.0.0"),
        http_port=_int("HTTP_PORT", 8088),
        scheduler_api_key=os.environ.get("SCHEDULER_API_KEY", ""),
        admin_username=os.environ.get("ADMIN_USERNAME", "admin"),
        admin_password=os.environ.get("ADMIN_PASSWORD", "admin"),
        phase1_enabled=_bool("PHASE1_ENABLED", True),
        phase1_interval_sec=_int("PHASE1_INTERVAL_SEC", 86400),
        phase1_concurrency=_int("PHASE1_CONCURRENCY", 4),
        phase2_enabled=_bool("PHASE2_ENABLED", False),
        phase2_interval_sec=_int("PHASE2_INTERVAL_SEC", 86400),
        phase2_scan_certs=_bool("PHASE2_SCAN_CERTS", True),
        phase3_enabled=_bool("PHASE3_ENABLED", False),
        phase3_interval_sec=_int("PHASE3_INTERVAL_SEC", 300),
        phase3_scan_certs=_bool("PHASE3_SCAN_CERTS", False),
        dry_run=_bool("DRY_RUN", False),
        http_timeout_sec=_int("HTTP_TIMEOUT_SEC", 60),
        max_retries=_int("MAX_RETRIES", 5),
        changed_by=os.environ.get("CHANGED_BY", "tdr-scheduler"),
    )
