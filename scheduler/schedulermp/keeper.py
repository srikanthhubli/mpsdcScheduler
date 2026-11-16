"""Keep the scheduler running in the background and restart it if it exits."""

from __future__ import annotations

import os
import signal
import subprocess
import sys
import time
from pathlib import Path

SERVICE = "tdr-scheduler"
RESTART_SEC = 3


def package_root() -> Path:
    return Path(__file__).resolve().parents[1]


def run_dir() -> Path:
    raw = os.environ.get("SCHEDULER_RUN_DIR", "")
    path = Path(raw) if raw else package_root() / "data"
    path.mkdir(parents=True, exist_ok=True)
    return path


def keeper_pid_path() -> Path:
    return run_dir() / "keeper.pid"


def serve_pid_path() -> Path:
    return run_dir() / "serve.pid"


def log_path() -> Path:
    return run_dir() / "scheduler.log"


def read_pid(path: Path) -> int:
    try:
        return int(path.read_text(encoding="utf-8").strip())
    except (OSError, ValueError):
        return 0


def alive(pid: int) -> bool:
    if pid <= 0:
        return False
    try:
        os.kill(pid, 0)
    except OSError:
        return False
    return True


def write_pid(path: Path, pid: int) -> None:
    path.write_text(str(pid), encoding="utf-8")


def clear_pid(path: Path) -> None:
    try:
        path.unlink()
    except OSError:
        return


def systemd_unit_installed() -> bool:
    systemctl = _systemctl()
    if not systemctl:
        return False
    result = subprocess.run([systemctl, "cat", f"{SERVICE}.service"], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    return result.returncode == 0


def _systemctl() -> str:
    for folder in os.environ.get("PATH", "").split(os.pathsep):
        candidate = Path(folder) / "systemctl"
        if candidate.is_file() and os.access(candidate, os.X_OK):
            return str(candidate)
    return ""


def run(args) -> None:
    command = args.command
    if command == "start":
        start()
    elif command == "stop":
        stop()
    elif command == "restart":
        stop()
        start()
    elif command == "status":
        status()
    elif command == "logs":
        logs(args.follow)
    elif command == "install":
        install()


def start() -> None:
    if systemd_unit_installed():
        subprocess.check_call([_systemctl(), "start", SERVICE])
        status()
        return
    if alive(read_pid(keeper_pid_path())):
        print("scheduler is already running")
        status()
        return
    first = os.fork()
    if first > 0:
        for _ in range(30):
            if alive(read_pid(keeper_pid_path())):
                status()
                return
            time.sleep(0.1)
        print("scheduler did not stay running; see", log_path())
        sys.exit(1)
    os.setsid()
    if os.fork() > 0:
        os._exit(0)
    os.chdir(package_root())
    null = os.open(os.devnull, os.O_RDONLY)
    os.dup2(null, 0)
    os.close(null)
    handle = open(log_path(), "a", encoding="utf-8", buffering=1)
    os.dup2(handle.fileno(), 1)
    os.dup2(handle.fileno(), 2)
    write_pid(keeper_pid_path(), os.getpid())
    _supervise()


def _supervise() -> None:
    stopping = {"value": False}
    current: dict[str, subprocess.Popen | None] = {"proc": None}

    def shutdown(signum, _frame) -> None:
        stopping["value"] = True
        proc = current["proc"]
        if proc is not None and proc.poll() is None:
            proc.terminate()

    signal.signal(signal.SIGTERM, shutdown)
    signal.signal(signal.SIGINT, shutdown)
    env = os.environ.copy()
    env["PYTHONUNBUFFERED"] = "1"
    while not stopping["value"]:
        print(f"scheduler starting", flush=True)
        proc = subprocess.Popen([sys.executable, "-m", "schedulermp", "serve"], cwd=package_root(), env=env)
        current["proc"] = proc
        write_pid(serve_pid_path(), proc.pid)
        code = proc.wait()
        clear_pid(serve_pid_path())
        if stopping["value"]:
            break
        print(f"scheduler exited {code}, restarting in {RESTART_SEC}s", flush=True)
        time.sleep(RESTART_SEC)
    clear_pid(keeper_pid_path())


def stop() -> None:
    if systemd_unit_installed():
        subprocess.check_call([_systemctl(), "stop", SERVICE])
        print("scheduler stopped")
        return
    keeper = read_pid(keeper_pid_path())
    serve = read_pid(serve_pid_path())
    if not alive(keeper) and not alive(serve):
        clear_pid(keeper_pid_path())
        clear_pid(serve_pid_path())
        print("scheduler is not running")
        return
    for pid in (keeper, serve):
        if alive(pid):
            os.kill(pid, signal.SIGTERM)
    deadline = time.time() + 10
    while time.time() < deadline and (alive(keeper) or alive(serve)):
        time.sleep(0.1)
    for pid in (keeper, serve):
        if alive(pid):
            os.kill(pid, signal.SIGKILL)
    clear_pid(keeper_pid_path())
    clear_pid(serve_pid_path())
    print("scheduler stopped")


def status() -> None:
    if systemd_unit_installed():
        systemctl = _systemctl()
        active = subprocess.run([systemctl, "is-active", SERVICE], capture_output=True, text=True)
        state = active.stdout.strip() or "unknown"
        pid = subprocess.run([systemctl, "show", "-p", "MainPID", "--value", SERVICE], capture_output=True, text=True)
        print(f"service: {SERVICE}")
        print(f"status: {state}")
        print(f"pid: {pid.stdout.strip() or '-'}")
        print(f"log: journalctl -u {SERVICE} -f")
        return
    keeper = read_pid(keeper_pid_path())
    serve = read_pid(serve_pid_path())
    if not alive(keeper):
        print("status: stopped")
        return
    print("status: running")
    print(f"keeper: {keeper}")
    print(f"scheduler: {serve if alive(serve) else '-'}")
    print(f"log: {log_path()}")


def logs(follow: bool) -> None:
    if systemd_unit_installed():
        command = ["journalctl", "-u", SERVICE, "-n", "100"]
        if follow:
            command.append("-f")
        os.execvp(command[0], command)
    path = log_path()
    if not path.exists():
        print(f"no log yet at {path}")
        return
    command = ["tail", "-n", "100", str(path)]
    if follow:
        command.insert(1, "-f")
    os.execvp(command[0], command)


def install() -> None:
    systemctl = _systemctl()
    if not systemctl:
        print("systemd is not available on this host. Use: python3 -m schedulermp start")
        sys.exit(1)
    if alive(read_pid(keeper_pid_path())):
        print("Stop the background scheduler first: python3 -m schedulermp stop")
        sys.exit(1)
    root = package_root()
    unit = f"""[Unit]
Description=TDR blockchain scheduler
After=network-online.target
Wants=network-online.target

[Service]
Type=simple
WorkingDirectory={root}
ExecStart={sys.executable} -m schedulermp serve
Restart=always
RestartSec={RESTART_SEC}
Environment=PYTHONUNBUFFERED=1

[Install]
WantedBy=multi-user.target
"""
    destination = Path("/etc/systemd/system") / f"{SERVICE}.service"
    destination.write_text(unit, encoding="utf-8")
    subprocess.check_call([systemctl, "daemon-reload"])
    subprocess.check_call([systemctl, "enable", "--now", SERVICE])
    print(f"installed {destination}")
    status()
