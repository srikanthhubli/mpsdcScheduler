from __future__ import annotations

import json
import os
import threading
from datetime import datetime, timezone


def utc_now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


class StateStore:
    def __init__(self, path: str):
        self.path = path
        self._lock = threading.Lock()
        self._write_lock = threading.Lock()
        self._generation = 0
        self.data = self._load()

    def _load(self) -> dict:
        if not os.path.exists(self.path):
            return {"verifications": {}, "jobs": {}}
        with open(self.path, "r", encoding="utf-8") as handle:
            loaded = json.load(handle)
        loaded.setdefault("verifications", {})
        loaded.setdefault("jobs", {})
        loaded.setdefault("schedule", None)
        return loaded

    def _save(self) -> None:
        payload, generation = self._payload()
        self._write(payload, generation)

    def _payload(self) -> tuple[str, int]:
        self._generation += 1
        return json.dumps(self.data, indent=2, ensure_ascii=False), self._generation

    def _write(self, payload: str, generation: int) -> None:
        with self._write_lock:
            with self._lock:
                if generation != self._generation:
                    return
            folder = os.path.dirname(self.path)
            if folder:
                os.makedirs(folder, exist_ok=True)
            temp = self.path + ".tmp"
            with open(temp, "w", encoding="utf-8") as handle:
                handle.write(payload)
            os.replace(temp, self.path)

    def snapshot(self) -> dict:
        with self._lock:
            verifications = {key: dict(row) for key, row in self.data["verifications"].items()}
            jobs = json.loads(json.dumps(self.data["jobs"]))
            schedule = json.loads(json.dumps(self.data.get("schedule"))) if self.data.get("schedule") else None
        return {"verifications": verifications, "jobs": jobs, "schedule": schedule}

    def verification(self, certificate_no: str) -> dict | None:
        with self._lock:
            row = self.data["verifications"].get(certificate_no)
            return dict(row) if row else None

    def save_verification(self, certificate_no: str, record: dict) -> dict:
        record = {**record, "certificate_no": certificate_no, "checked_at": record.get("checked_at") or utc_now()}
        with self._lock:
            self.data["verifications"][certificate_no] = record
            payload, generation = self._payload()
        self._write(payload, generation)
        return dict(record)

    def job(self, key: str) -> dict | None:
        with self._lock:
            row = self.data["jobs"].get(key)
            return json.loads(json.dumps(row)) if row else None

    def save_job(self, key: str, record: dict) -> dict:
        with self._lock:
            self.data["jobs"][key] = record
            payload, generation = self._payload()
            saved = json.loads(json.dumps(record))
        self._write(payload, generation)
        return saved

    def schedule(self) -> dict:
        with self._lock:
            current = self.data.get("schedule")
            return json.loads(json.dumps(current)) if current else {}

    def save_schedule(self, schedule: dict) -> dict:
        with self._lock:
            self.data["schedule"] = schedule
            payload, generation = self._payload()
            saved = json.loads(json.dumps(schedule))
        self._write(payload, generation)
        return saved

    def claim_field(self, group: str, field: str, value: str) -> bool:
        with self._lock:
            current = self.data.get("schedule") or {}
            row = current.setdefault(group, {})
            if row.get(field) == value:
                return False
            row[field] = value
            self.data["schedule"] = current
            payload, generation = self._payload()
        self._write(payload, generation)
        return True

    def release_field(self, group: str, field: str, value: str) -> None:
        with self._lock:
            current = self.data.get("schedule") or {}
            row = current.get(group) or {}
            if row.get(field) != value:
                return
            row[field] = ""
            self.data["schedule"] = current
            payload, generation = self._payload()
        self._write(payload, generation)
