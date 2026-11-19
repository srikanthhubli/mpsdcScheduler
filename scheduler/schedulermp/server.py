from __future__ import annotations

import json
import logging
import mimetypes
import secrets
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlparse

FRONTEND_DIR = Path(__file__).resolve().parents[2] / "frontend"
STATIC_FILES = {
    "/": "index.html",
    "/index.html": "index.html",
    "/app.js": "app.js",
    "/styles.css": "styles.css",
}

from schedulermp.clock import (
    active_window,
    default_schedule,
    legacy_finished,
    legacy_open_count,
    normalize_schedule,
)
from schedulermp.http_client import ApiError
from schedulermp.phase1 import run_phase1, verifications_csv
from schedulermp.pipeline import SyncService
from schedulermp.runs import RunBoard, RunBusy

log = logging.getLogger("schedulermp.server")


class SchedulerApp:
    def __init__(self, settings, tdr, chain, store):
        self.settings = settings
        self.tdr = tdr
        self.chain = chain
        self.store = store
        self.sync = SyncService(settings, tdr, chain, store)
        self.stop = threading.Event()
        self.locks = {name: threading.Lock() for name in ("phase1", "phase2", "phase3")}
        self.sessions: set[str] = set()
        self.runs = RunBoard()
        self._threads = []

    def start_loops(self) -> None:
        if not self.settings.phase1_enabled:
            return
        thread = threading.Thread(
            target=self._loop,
            args=("phase1_interval_sec", self._auto_phase1),
            name="phase1",
            daemon=True,
        )
        thread.start()
        self._threads.append(thread)

    def start_clock(self) -> None:
        thread = threading.Thread(target=self._clock, name="clock", daemon=True)
        thread.start()
        self._threads.append(thread)

    def _loop(self, interval_attr: str, action) -> None:
        interval = max(1, getattr(self.settings, interval_attr))
        while not self.stop.wait(interval):
            try:
                action()
            except Exception:
                log.exception("scheduled run failed")

    def _auto_phase1(self) -> None:
        self.run_phase1()

    def current_schedule(self) -> dict:
        stored = self.store.schedule()
        schedule = normalize_schedule(stored or default_schedule())
        if not stored:
            self.store.save_schedule(schedule)
        return schedule

    def update_schedule(self, payload: dict) -> dict:
        merged = normalize_schedule({**self.current_schedule(), **(payload or {})})
        if "legacy" in (payload or {}):
            merged["legacy"] = normalize_schedule({"legacy": payload["legacy"]})["legacy"]
            merged["legacy"]["lastWindow"] = self.current_schedule()["legacy"].get("lastWindow", "")
            merged["legacy"]["automatic"] = self.current_schedule()["legacy"].get("automatic", False)
            merged["legacy"]["message"] = (
                f"On. Each day at {merged['legacy']['start']} for {merged['legacy']['hours']} hour(s)."
                if merged["legacy"]["enabled"]
                else "Legacy daily schedule is off."
            )
        saved = self.store.save_schedule(merged)
        return self.schedule_view(saved)

    def schedule_view(self, schedule: dict | None = None) -> dict:
        from datetime import datetime
        from zoneinfo import ZoneInfo

        schedule = schedule or self.current_schedule()
        now = datetime.now(ZoneInfo(schedule["timezone"]))
        window = None
        if schedule["legacy"]["enabled"]:
            window = active_window(now, schedule["legacy"]["start"], schedule["legacy"]["hours"])
        return {
            "schedule": schedule,
            "now": now.isoformat(),
            "legacyWindowOpen": window is not None,
            "legacyWindow": [window[0].isoformat(), window[1].isoformat()] if window else None,
        }

    def _clock(self) -> None:
        while not self.stop.wait(20):
            try:
                self._tick()
            except Exception:
                log.exception("schedule tick failed")

    def _tick(self) -> None:
        from datetime import datetime
        from zoneinfo import ZoneInfo

        schedule = self.current_schedule()
        now = datetime.now(ZoneInfo(schedule["timezone"]))
        legacy = schedule["legacy"]
        if legacy["enabled"]:
            window = active_window(now, legacy["start"], legacy["hours"])
            if window:
                key = window[0].date().isoformat()
                if legacy.get("lastWindow") != key and self.store.claim_field("legacy", "lastWindow", key):
                    log.info("legacy window %s claimed for %s hour(s) from %s", key, legacy["hours"], legacy["start"])
                    threading.Thread(
                        target=self._scheduled_legacy,
                        args=(key,),
                        name="legacy-window",
                        daemon=True,
                    ).start()
            else:
                self._stop_scheduled(2, "legacy")

    def _release_claim(self, group: str, field: str, value: str) -> None:
        self.store.release_field(group, field, value)

    def _scheduled_legacy(self, window_key: str) -> None:
        self._mark_automatic(True)
        try:
            result = self.run_phase2()
        except RunBusy:
            log.info("legacy window %s left unclaimed because phase 2 is already running", window_key)
            self._release_claim("legacy", "lastWindow", window_key)
            return
        except Exception as exc:
            log.exception("legacy window %s failed", window_key)
            self._note("legacy", f"Legacy window failed: {exc}")
            return
        finally:
            self._mark_automatic(False)
        self._after_legacy(result, one_shot=False)

    def _mark_automatic(self, value: bool) -> None:
        schedule = self.current_schedule()
        schedule["legacy"]["automatic"] = value
        self.store.save_schedule(schedule)

    def _stop_scheduled(self, phase: int, group: str) -> None:
        control = self.runs.control(phase)
        if control is None:
            return
        status = control.snapshot().get("status")
        if status not in {"RUNNING", "EXTRACTING", "PAUSED"}:
            return
        if not self.current_schedule()["legacy"].get("automatic"):
            return
        control.request_stop()
        self._note(group, "The daily window ended. Work stops after the current step and continues next day.")

    def _after_legacy(self, result: dict, one_shot: bool) -> None:
        items = (result.get("run") or {}).get("items") or []
        if one_shot:
            self._disable_legacy(
                f"One-shot legacy run finished {result.get('count', 0)} application(s). Daily legacy schedule is off."
            )
            return
        schedule = self.current_schedule()
        if schedule["legacy"].get("stopWhenComplete") and legacy_finished(items):
            self._disable_legacy("Every legacy application is on the blockchain. Daily legacy schedule is off.")
            return
        open_count = legacy_open_count(items)
        if items:
            self._note("legacy", f"{open_count} application(s) still open. The next daily window continues them.")

    def _disable_legacy(self, message: str) -> None:
        schedule = self.current_schedule()
        schedule["legacy"]["enabled"] = False
        schedule["legacy"]["message"] = message
        self.store.save_schedule(schedule)

    def _note(self, group: str, message: str) -> None:
        schedule = self.current_schedule()
        schedule[group]["message"] = message
        self.store.save_schedule(schedule)

    def _launch(self, phase: int, worker) -> dict:
        lock = self.locks[f"phase{phase}"]
        if not lock.acquire(blocking=False):
            raise RunBusy(f"Phase {phase} is already running")
        control = self.runs.attach(phase)

        def wrapped() -> None:
            try:
                worker(control)
            except Exception as exc:
                log.exception("phase %s failed", phase)
                control.fail(str(exc))
            finally:
                lock.release()

        threading.Thread(target=wrapped, name=f"phase{phase}", daemon=True).start()
        log.info("phase %s started in the background", phase)
        return {
            "status": "STARTED",
            "message": f"Phase {phase} started. Progress stays on the Run screen and in the scheduler log.",
            "run": control.snapshot(),
        }

    def _finish_phase1(self, control, certificate_no: str, limit: int) -> dict:
        result = run_phase1(
            self.tdr,
            self.chain,
            self.store,
            certificate_no=certificate_no,
            limit=limit,
            concurrency=self.settings.phase1_concurrency,
            control=control,
        )
        summary = result["summary"]
        if result.get("stopped"):
            message = (
                f"Phase 1 stopped. {summary['MATCH']} match, {summary['MISMATCH']} mismatch, "
                f"{summary['NOT_FOUND']} not found, {summary['API_FAILURE']} API failure."
            )
        else:
            message = (
                f"Phase 1 finished. {summary['MATCH']} match, {summary['MISMATCH']} mismatch, "
                f"{summary['NOT_FOUND']} not found, {summary['API_FAILURE']} API failure."
            )
        control.complete(message)
        log.info(message)
        result["run"] = control.snapshot()
        return result

    def run_phase1(self, certificate_no: str = "", limit: int = 0, background: bool = False) -> dict:
        if background:
            return self._launch(1, lambda control: self._finish_phase1(control, certificate_no, limit))
        with self.locks["phase1"]:
            control = self.runs.attach(1)
            try:
                return self._finish_phase1(control, certificate_no, limit)
            except Exception as exc:
                control.fail(str(exc))
                raise

    def run_phase2(self, application_id: str = "", limit: int = 0, force: bool = False, one_shot: bool = False, background: bool = False) -> dict:
        if background:
            return self._launch(
                2,
                lambda control: self._finish_phase2(control, application_id, limit, force, one_shot),
            )
        if not self.locks["phase2"].acquire(blocking=False):
            raise RunBusy("Phase 2 is already running")
        control = self.runs.attach(2)
        try:
            return self._finish_phase2(control, application_id, limit, force, one_shot)
        except Exception as exc:
            control.fail(str(exc))
            raise
        finally:
            self.locks["phase2"].release()

    def _finish_phase2(self, control, application_id: str, limit: int, force: bool, one_shot: bool) -> dict:
        results = self.sync.run_legacy_batch(application_id, limit, force, control=control)
        stopped = control._stop.is_set()
        control.complete("Phase 2 stopped" if stopped else "Phase 2 finished")
        counts = control.snapshot()["counts"]
        message = (
            f"{'Phase 2 stopped' if stopped else 'Phase 2 finished'}. "
            f"{counts.get('SUCCESS', 0)} succeeded, {counts.get('FAILED', 0)} failed, "
            f"{counts.get('SKIPPED', 0)} skipped, {counts.get('NOT_STARTED', 0)} not started."
        )
        with control._lock:
            control.state["message"] = message
            control._log(message)
        log.info(message)
        result = {"count": len(results), "jobs": results, "run": control.snapshot()}
        self._after_legacy(result, one_shot=one_shot)
        return result

    def run_phase3(
        self,
        application_id: str = "",
        owner_ids: list[str] | None = None,
        certificate_nos: list[str] | None = None,
        force: bool = False,
        limit: int = 0,
        background: bool = False,
    ) -> dict:
        if background:
            return self._launch(
                3,
                lambda control: self._finish_phase3(control, application_id, owner_ids, certificate_nos, force, limit),
            )
        if not self.locks["phase3"].acquire(blocking=False):
            raise RunBusy("Phase 3 is already running")
        control = self.runs.attach(3)
        try:
            return self._finish_phase3(control, application_id, owner_ids, certificate_nos, force, limit)
        except Exception as exc:
            control.fail(str(exc))
            raise
        finally:
            self.locks["phase3"].release()

    def _finish_phase3(self, control, application_id, owner_ids, certificate_nos, force, limit) -> dict:
        if application_id:
            control.note(f"Using application {application_id}")
            control.extracted([application_id])
            if control.should_continue():
                control.begin(application_id, 1)
                job = self.sync.run_application(
                    "live",
                    application_id,
                    owner_ids or [],
                    certificate_nos or [],
                    force=force,
                    control=control,
                )
                results = [job]
            else:
                results = []
        else:
            results = self.sync.run_live_batch(limit, control=control)
        stopped = control._stop.is_set()
        control.complete("Phase 3 stopped" if stopped else "Phase 3 finished")
        counts = control.snapshot()["counts"]
        message = (
            f"{'Phase 3 stopped' if stopped else 'Phase 3 finished'}. "
            f"{counts.get('SUCCESS', 0)} succeeded, {counts.get('FAILED', 0)} failed, "
            f"{counts.get('SKIPPED', 0)} skipped, {counts.get('NOT_STARTED', 0)} not started."
        )
        with control._lock:
            control.state["message"] = message
            control._log(message)
        log.info(message)
        return {"count": len(results), "jobs": results, "run": control.snapshot()}

    def run_command(self, phase: int, action: str) -> dict:
        control = self.runs.control(phase)
        if control is None:
            raise RunBusy(f"Phase {phase} has no run to {action}")
        changed = getattr(control, action)()
        log.info("phase %s %s accepted=%s", phase, action, changed)
        snapshot = control.snapshot()
        if not changed:
            snapshot["accepted"] = False
        return snapshot

    def status(self) -> dict:
        snap = self.store.snapshot()
        verifications = list(snap["verifications"].values())
        counts = {}
        for row in verifications:
            counts[row.get("status", "UNKNOWN")] = counts.get(row.get("status", "UNKNOWN"), 0) + 1
        jobs = {}
        for row in snap["jobs"].values():
            jobs[row.get("status", "UNKNOWN")] = jobs.get(row.get("status", "UNKNOWN"), 0) + 1
        return {
            "phase1_enabled": self.settings.phase1_enabled,
            "phase2_enabled": self.current_schedule()["legacy"]["enabled"],
            "phase3_enabled": self.settings.phase3_enabled,
            "schedule": self.schedule_view(),
            "dry_run": self.settings.dry_run,
            "verifications": counts,
            "jobs": jobs,
        }


def make_handler(app: SchedulerApp):
    class Handler(BaseHTTPRequestHandler):
        protocol_version = "HTTP/1.1"

        def log_message(self, fmt, *args):
            path = urlparse(self.path).path
            status = args[1] if len(args) > 1 else ""
            if path in STATIC_FILES or path in {"/runs", "/health", "/status"}:
                log.debug("%s %s %s", self.command, path, status)
                return
            log.info("%s %s %s", self.command, path, status)

        def _authorized(self) -> bool:
            header = self.headers.get("Authorization", "")
            token = header[7:].strip() if header.lower().startswith("bearer ") else ""
            token = token or self.headers.get("X-Scheduler-Token", "")
            if token and token in app.sessions:
                return True
            expected = app.settings.scheduler_api_key
            if expected and self.headers.get("X-API-Key", "") == expected:
                return True
            self._json(401, {"status": "FAILED", "message": "Login required"})
            return False

        def _json(self, status: int, payload: dict) -> None:
            raw = json.dumps(payload, ensure_ascii=False).encode("utf-8")
            self.send_response(status)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(raw)))
            self.send_header("Access-Control-Allow-Origin", "*")
            self.send_header("Access-Control-Allow-Headers", "Content-Type, Authorization, X-API-Key, X-Scheduler-Token")
            self.send_header("Access-Control-Allow-Methods", "GET, POST, OPTIONS")
            self.end_headers()
            self.wfile.write(raw)

        def do_OPTIONS(self):
            self.send_response(204)
            self.send_header("Access-Control-Allow-Origin", "*")
            self.send_header("Access-Control-Allow-Headers", "Content-Type, Authorization, X-API-Key, X-Scheduler-Token")
            self.send_header("Access-Control-Allow-Methods", "GET, POST, OPTIONS")
            self.send_header("Content-Length", "0")
            self.end_headers()

        def _query(self) -> dict:
            parsed = urlparse(self.path)
            query = parse_qs(parsed.query)
            return {key: values[-1] for key, values in query.items()}

        def _body(self) -> dict:
            length = int(self.headers.get("Content-Length") or 0)
            if length <= 0:
                return {}
            raw = self.rfile.read(length)
            if not raw:
                return {}
            loaded = json.loads(raw.decode("utf-8"))
            if not isinstance(loaded, dict):
                raise ValueError("Request body must be a JSON object")
            return loaded

        def _file(self, path: str) -> bool:
            name = STATIC_FILES.get(path)
            if not name:
                return False
            file_path = FRONTEND_DIR / name
            if not file_path.is_file():
                self._json(404, {"status": "NOT_FOUND", "message": f"dashboard file {name} is missing"})
                return True
            raw = file_path.read_bytes()
            mime = mimetypes.guess_type(name)[0] or "application/octet-stream"
            self.send_response(200)
            self.send_header("Content-Type", mime)
            self.send_header("Content-Length", str(len(raw)))
            self.send_header("Access-Control-Allow-Origin", "*")
            self.end_headers()
            self.wfile.write(raw)
            return True

        def do_GET(self):
            parsed = urlparse(self.path)
            if self._file(parsed.path):
                return
            if not self._authorized():
                return
            try:
                self._get(parsed)
            except Exception as exc:
                self._fail(exc)

        def _get(self, parsed):
            query = self._query()
            if parsed.path == "/health":
                self._json(200, {"status": "ok"})
                return
            if parsed.path == "/status":
                self._json(200, app.status())
                return
            if parsed.path == "/verifications":
                snap = app.store.snapshot()["verifications"]
                if query.get("certificate"):
                    row = snap.get(query["certificate"])
                    self._json(200 if row else 404, row or {"status": "NOT_FOUND", "message": "No stored verification for that certificate"})
                    return
                self._json(200, {"count": len(snap), "verifications": snap})
                return
            if parsed.path == "/verifications.csv":
                snap = app.store.snapshot()["verifications"]
                if str(query.get("onChain") or "").lower() in {"1", "true", "yes"}:
                    snap = {
                        key: row
                        for key, row in snap.items()
                        if row.get("on_chain") or row.get("status") == "MATCH"
                    }
                raw = verifications_csv(snap).encode("utf-8")
                name = "phase1-on-chain.csv" if query.get("onChain") else "phase1-verifications.csv"
                self.send_response(200)
                self.send_header("Content-Type", "text/csv; charset=utf-8")
                self.send_header("Content-Disposition", f'attachment; filename="{name}"')
                self.send_header("Content-Length", str(len(raw)))
                self.send_header("Access-Control-Allow-Origin", "*")
                self.end_headers()
                self.wfile.write(raw)
                return
            if parsed.path == "/jobs":
                snap = app.store.snapshot()["jobs"]
                if query.get("applicationId"):
                    mode = query.get("mode", "live")
                    if mode not in {"live", "legacy"}:
                        raise ValueError("mode must be live or legacy")
                    row = snap.get(f"{mode}:{query['applicationId']}")
                    self._json(200 if row else 404, row or {"status": "NOT_FOUND", "message": "No stored job for that application"})
                    return
                self._json(200, {"count": len(snap), "jobs": snap})
                return
            if parsed.path == "/runs":
                self._json(200, {"runs": app.runs.snapshot()})
                return
            if parsed.path == "/schedule":
                self._json(200, app.schedule_view())
                return
            self._json(404, {"status": "NOT_FOUND", "message": "unknown path"})

        def do_POST(self):
            parsed = urlparse(self.path)
            try:
                body = self._body()
            except json.JSONDecodeError:
                self._json(400, {"status": "FAILED", "message": "Request body is not valid JSON"})
                return
            except ValueError as exc:
                self._json(400, {"status": "FAILED", "message": str(exc)})
                return
            if parsed.path == "/login":
                username = str(body.get("username") or "")
                password = str(body.get("password") or "")
                user_ok = secrets.compare_digest(username, app.settings.admin_username)
                pass_ok = secrets.compare_digest(password, app.settings.admin_password)
                if not (user_ok and pass_ok):
                    log.warning("login failed for %s", username or "(blank)")
                    self._json(401, {"status": "FAILED", "message": "Invalid username or password"})
                    return
                token = secrets.token_urlsafe(32)
                app.sessions.add(token)
                log.info("login succeeded for %s", username)
                self._json(200, {"status": "SUCCESS", "username": username, "token": token})
                return
            if not self._authorized():
                return
            if parsed.path == "/logout":
                header = self.headers.get("Authorization", "")
                token = header[7:].strip() if header.lower().startswith("bearer ") else ""
                app.sessions.discard(token)
                self._json(200, {"status": "SUCCESS", "message": "Signed out"})
                return
            try:
                query = self._query()
                limit = _limit(body, query)
                force = _flag(body.get("force") if "force" in body else query.get("force"))
                background = _flag(body.get("background") or query.get("background"))
                if parsed.path == "/run/phase1":
                    result = app.run_phase1(
                        _text(body.get("certificate") or query.get("certificate")),
                        limit,
                        background=background,
                    )
                    self._json(200, result)
                    return
                if parsed.path == "/run/phase2":
                    result = app.run_phase2(
                        _text(body.get("applicationId") or query.get("applicationId")),
                        limit,
                        force,
                        one_shot=_flag(body.get("oneShot") or query.get("oneShot")),
                        background=background,
                    )
                    self._json(200, result)
                    return
                if parsed.path == "/schedule":
                    self._json(200, app.update_schedule(body))
                    return
                if parsed.path == "/run/phase3":
                    result = app.run_phase3(
                        _text(body.get("applicationId") or query.get("applicationId")),
                        _id_list(body.get("ownerIds"), "ownerIds"),
                        _id_list(body.get("certificateNos"), "certificateNos"),
                        force,
                        limit,
                        background=background,
                    )
                    self._json(200, result)
                    return
                action = _run_action(parsed.path)
                if action:
                    phase, name = action
                    self._json(200, app.run_command(phase, name))
                    return
            except RunBusy as exc:
                log.info("%s busy: %s", parsed.path, exc)
                self._json(409, {"status": "FAILED", "message": str(exc)})
                return
            except ValueError as exc:
                self._json(400, {"status": "FAILED", "message": str(exc)})
                return
            except ApiError as exc:
                log.warning("upstream call failed: %s", exc.message)
                self._json(502, {"status": "FAILED", "message": exc.message, "retryable": exc.retryable})
                return
            except Exception as exc:
                self._fail(exc)
                return
            self._json(404, {"status": "NOT_FOUND", "message": "unknown path"})

        def _fail(self, exc: Exception) -> None:
            log.exception("request failed")
            try:
                self._json(500, {"status": "FAILED", "message": str(exc) or "The scheduler could not complete the request"})
            except Exception:
                log.exception("could not write the error response")

    return Handler


def _text(value) -> str:
    return str(value or "").strip()


def _flag(value) -> bool:
    return value is True or str(value or "").lower() in {"1", "true", "yes"}


def _limit(body: dict, query: dict) -> int:
    raw = body.get("limit")
    if raw in (None, ""):
        raw = query.get("limit") or 0
    try:
        value = int(raw)
    except (TypeError, ValueError):
        raise ValueError("limit must be a whole number") from None
    if value < 0:
        raise ValueError("limit must be 0 or greater")
    return value


def _id_list(value, name: str) -> list[str]:
    if value in (None, ""):
        return []
    if isinstance(value, str):
        return [part.strip() for part in value.split(",") if part.strip()]
    if isinstance(value, list):
        return [str(item).strip() for item in value if str(item).strip()]
    raise ValueError(f"{name} must be a list or a comma-separated string")


def _run_action(path: str) -> tuple[int, str] | None:
    parts = path.strip("/").split("/")
    if len(parts) != 3 or parts[0] != "runs":
        return None
    phase = {"phase1": 1, "phase2": 2, "phase3": 3}.get(parts[1])
    action = {"pause": "pause", "resume": "resume", "stop": "request_stop"}.get(parts[2])
    if phase and action:
        return phase, action
    return None


def serve(app: SchedulerApp) -> None:
    app.start_loops()
    app.start_clock()
    server = ThreadingHTTPServer((app.settings.http_host, app.settings.http_port), make_handler(app))
    log.info(
        "scheduler listening on %s:%s dry_run=%s phase1=%s",
        app.settings.http_host,
        app.settings.http_port,
        app.settings.dry_run,
        app.settings.phase1_enabled,
    )
    try:
        server.serve_forever()
    finally:
        app.stop.set()
        server.server_close()
