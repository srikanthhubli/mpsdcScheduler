# TDR blockchain scheduler

One Python process serves the scheduler API and the admin screen. There is no separate frontend server. Python 3.9 or newer is enough. Node is not required.

How to check each screen: [TESTING.md](TESTING.md).

How the stages move: [FLOW.md](FLOW.md).

URL, body, internal calls, checks, and output for each scheduler API: [API-CONTRACT.md](API-CONTRACT.md).

Which TDR and MPSDC API belongs to which use case: [API-USE-CASES.md](API-USE-CASES.md).

## Run the scheduler and the screen

```bash
cd scheduler
cp .env.example .env
```

Edit `.env` before the first start:

- `BLOCKCHAIN_API_KEY` is the MPSDC `X-API-Key`.
- `ADMIN_USERNAME` and `ADMIN_PASSWORD` sign in to the screen. The sample values are `admin` and `admin`. Change the password on the server.
- `HTTP_HOST=0.0.0.0` and `HTTP_PORT=8088` let a browser on another machine open the screen. The screen is served from the `frontend/` folder.

Foreground, useful while you watch the log in the same terminal:

```bash
cd scheduler
python3 -m schedulermp serve
```

Background, so the terminal can close and the process comes back if it exits:

```bash
cd scheduler
chmod +x tdrctl
./tdrctl start
./tdrctl status
./tdrctl logs -f
```

`./tdrctl restart` stops it and starts it again. `./tdrctl stop` stops it. The log file is `scheduler/data/scheduler.log`.

To start it again after a reboot, as root:

```bash
cd scheduler
python3 -m schedulermp install
```

That registers the systemd service `tdr-scheduler`. After that, `./tdrctl start`, `stop`, `status`, and `logs` control the service.

## Open the screen

Open `http://<server>:8088/` in a browser. Sign in with the admin user from `.env`.

Open that URL, not the `frontend/index.html` file. The screen calls the scheduler on the same host and port. A file opened from disk cannot reach it.

Pass: the status pill reads **online**.

If the banner says it cannot reach the scheduler, nothing is listening on that host and port. Run `./tdrctl status`, then start it again.

- `scheduler/` — API, background control, and `.env`.
- `frontend/` — the admin screen files. The scheduler serves them at `/`.
- `scheduler/postman/TDR-Scheduler.postman_collection.json` — Login, then health, status, and the three phase runs. Set `baseUrl` to `http://<server>:8088`.
