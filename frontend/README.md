# Dashboard

This folder is the admin screen. It has no server of its own. The scheduler in `../scheduler/` serves these files at `http://<server>:8088/`.

## Run it

```bash
cd ../scheduler
cp .env.example .env
```

Set `BLOCKCHAIN_API_KEY`, `ADMIN_USERNAME`, and `ADMIN_PASSWORD` in `.env`.

Foreground:

```bash
python3 -m schedulermp serve
```

Background:

```bash
chmod +x tdrctl
./tdrctl start
```

Then open `http://<server>:8088/` in a browser and sign in. The sample user is `admin` / `admin`. Change that password on the server.

The browser must use the scheduler host and port. Opening `index.html` from disk shows a banner that it cannot reach the scheduler.

`./tdrctl status` shows whether the process is up. `./tdrctl logs -f` follows the log. `./tdrctl stop` stops the process and the screen with it.

Screen checks are in [TESTING.md](../TESTING.md).
