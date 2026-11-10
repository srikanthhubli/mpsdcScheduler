"""Live progress for a phase 2 or phase 3 run.

Pause and stop are checked between applications and between stages.
The HTTP call already in flight finishes before the run waits or exits.
"""

from __future__ import annotations

import threading

from schedulermp.store import utc_now

STAGE_LABELS = {
    "LOAD": "Reading TDR",
    "GENERATING_AREA": "Generating area",
    "OWNER_DETAIL": "Owners",
    "DRC_UPLOAD": "DRC upload",
    "TRANSFER": "Transfer",
}


class StopRequested(Exception):
    pass


class RunBusy(Exception):
    pass


def idle_run(phase: int) -> dict:
    return {
        "phase": phase,
        "status": "IDLE",
        "message": "No run yet",
        "extracted": [],
        "items": [],
        "counts": {},
        "log": [],
        "current": "",
        "index": 0,
        "total": 0,
        "stage": "",
        "detail": "",
        "startedAt": "",
        "finishedAt": "",
    }


class RunControl:
    def __init__(self, phase: int):
        self.phase = phase
        self._lock = threading.Lock()
        self._pause = threading.Event()
        self._pause.set()
        self._stop = threading.Event()
        self.state = idle_run(phase)
        self.state["status"] = "EXTRACTING"
        self.state["message"] = "Reading the TDR application list"
        self.state["startedAt"] = utc_now()

    def snapshot(self) -> dict:
        with self._lock:
            copy = {
                key: (value.copy() if isinstance(value, dict) else list(value) if isinstance(value, list) else value)
                for key, value in self.state.items()
            }
            copy["items"] = [dict(item) for item in self.state["items"]]
            copy["counts"] = _counts(copy["items"])
            return copy

    def note(self, message: str) -> None:
        with self._lock:
            self.state["message"] = message
            self._log(message)

    def extracted(self, application_ids: list[str]) -> None:
        with self._lock:
            self.state["extracted"] = list(application_ids)
            self.state["total"] = len(application_ids)
            self.state["items"] = [
                {"applicationId": app_id, "status": "PENDING", "stage": "", "message": "Waiting"}
                for app_id in application_ids
            ]
            if application_ids:
                self.state["status"] = "RUNNING"
                self.state["message"] = f"Extracted {len(application_ids)} application id(s)"
            else:
                self.state["status"] = "COMPLETED"
                self.state["message"] = "TDR returned no application ids"
                self.state["finishedAt"] = utc_now()
            self._log(self.state["message"])

    def begin(self, application_id: str, index: int) -> None:
        with self._lock:
            self.state["current"] = application_id
            self.state["index"] = index
            self.state["stage"] = ""
            self.state["detail"] = "Starting"
            if self.state["status"] not in {"PAUSED", "STOPPING"}:
                self.state["status"] = "RUNNING"
            self.state["message"] = f"Running {application_id} ({index} of {self.state['total']})"
            self._touch(application_id, "RUNNING", "", "Starting")
            self._log(self.state["message"])

    def detail(self, application_id: str, stage: str, message: str, log: bool = False) -> None:
        with self._lock:
            self.state["current"] = application_id or self.state["current"]
            self.state["stage"] = stage
            self.state["detail"] = message
            label = STAGE_LABELS.get(stage, stage)
            if self.state["status"] not in {"PAUSED", "STOPPING", "STOPPED"}:
                self.state["message"] = f"{self.state['current']} · {label} · {message}"
            self._touch(application_id, "RUNNING", stage, message)
            if log:
                self._log(f"{application_id} · {label}: {message}")

    def finish(self, application_id: str, status: str, message: str, stage: str = "") -> None:
        with self._lock:
            self._touch(application_id, status, stage, message)
            label = STAGE_LABELS.get(stage, stage)
            suffix = f" · {label}" if label else ""
            self._log(f"{application_id} {status}{suffix}: {message}")

    def complete(self, message: str) -> None:
        with self._lock:
            stopped = self._stop.is_set()
            for item in self.state["items"]:
                if item["status"] in {"PENDING", "RUNNING"}:
                    item["status"] = "NOT_STARTED" if item["status"] == "PENDING" else "STOPPED"
                    if item["status"] == "NOT_STARTED":
                        item["message"] = "Not started"
            self.state["status"] = "STOPPED" if stopped else "COMPLETED"
            self.state["message"] = message
            self.state["current"] = ""
            self.state["finishedAt"] = utc_now()
            self._log(message)

    def fail(self, message: str) -> None:
        with self._lock:
            self.state["status"] = "FAILED"
            self.state["message"] = message
            self.state["finishedAt"] = utc_now()
            self._log(message)

    def pause(self) -> bool:
        with self._lock:
            if self.state["status"] not in {"RUNNING", "EXTRACTING"}:
                return False
            self.state["status"] = "PAUSED"
            self.state["message"] = "Paused. The current step finishes, then the run waits."
            self._log(self.state["message"])
        self._pause.clear()
        return True

    def resume(self) -> bool:
        with self._lock:
            if self.state["status"] != "PAUSED":
                return False
            self.state["status"] = "RUNNING"
            self.state["message"] = "Resumed"
            self._log("Resumed")
        self._pause.set()
        return True

    def request_stop(self) -> bool:
        with self._lock:
            if self.state["status"] in {"COMPLETED", "STOPPED", "FAILED", "IDLE"}:
                return False
            self.state["status"] = "STOPPING"
            self.state["message"] = "Stopping after the current step"
            self._log(self.state["message"])
        self._stop.set()
        self._pause.set()
        return True

    def should_continue(self) -> bool:
        while not self._pause.is_set():
            if self._stop.wait(0.25):
                return False
        return not self._stop.is_set()

    def _touch(self, application_id: str, status: str, stage: str, message: str) -> None:
        for item in self.state["items"]:
            if item["applicationId"] == application_id:
                item["status"] = status
                item["stage"] = stage
                item["message"] = message
                return
        self.state["items"].append(
            {"applicationId": application_id, "status": status, "stage": stage, "message": message}
        )

    def _log(self, message: str) -> None:
        self.state["log"].append(f"{utc_now()}  {message}")
        del self.state["log"][:-80]


class RunBoard:
    def __init__(self):
        self._lock = threading.Lock()
        self._controls: dict[int, RunControl | None] = {2: None, 3: None}

    def attach(self, phase: int) -> RunControl:
        control = RunControl(phase)
        with self._lock:
            self._controls[phase] = control
        return control

    def control(self, phase: int) -> RunControl | None:
        with self._lock:
            return self._controls.get(phase)

    def snapshot(self) -> dict:
        return {"phase2": self._one(2), "phase3": self._one(3)}

    def _one(self, phase: int) -> dict:
        control = self.control(phase)
        return control.snapshot() if control else idle_run(phase)


def _counts(items: list[dict]) -> dict:
    counts: dict[str, int] = {}
    for item in items:
        status = item.get("status") or "UNKNOWN"
        counts[status] = counts.get(status, 0) + 1
    return counts
