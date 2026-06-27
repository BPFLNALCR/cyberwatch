# Local Development Workflow

This workflow assumes the cyberWatch repository is checked out at:

```bash
/mnt/c/Users/User/cyberwatch
```

Do not move, copy, or clone the repository for these commands. The scripts below
always `cd` to that exact path before doing any work.

## Codex-safe checks

Codex should use only non-privileged development scripts. These scripts do not
run `sudo`, do not run the installer, and do not run uninstall scripts.

```bash
cd /mnt/c/Users/User/cyberwatch
bash scripts/dev_test.sh
```

`scripts/dev_test.sh` uses `.venv/bin/python` when present, otherwise `python3`.
It runs:

```bash
python -m compileall cyberWatch
python -m pytest
```

For a broader local smoke check:

```bash
cd /mnt/c/Users/User/cyberwatch
bash scripts/dev_smoke.sh
```

The smoke script verifies:

- `python -m compileall cyberWatch`
- `python -m pytest`
- `import cyberWatch.enrichment.run_enrichment`
- `TargetQueue().queue_key == "cyberwatch:targets"`
- `GET /health` if the API is running on localhost
- `POST /settings/clear-dns` returns `403` if the API is running
- Redis queue lengths for `cyberwatch:targets` and legacy `cyberWatch:targets`
  if Redis is running

## Running the API for development

After dependencies are installed, start the API without elevated privileges:

```bash
cd /mnt/c/Users/User/cyberwatch
bash scripts/dev_api.sh
```

The script defaults to:

```bash
CYBERWATCH_ENABLE_DESTRUCTIVE_SETTINGS=false
CYBERWATCH_DNS_STORE_CLIENT_IPS=false
CYBERWATCH_PG_DSN=postgresql://cyberwatch_test:cyberwatch_test@localhost:5432/cyberwatch_test
CYBERWATCH_REDIS_URL=redis://localhost:6379/0
```

Override those variables in the shell when needed. Do not enable destructive
settings for normal development.

## Host install smoke

The installer requires host privileges and may install packages, apply schemas,
and install systemd units. Codex should not run it from the restricted sandbox.
Run it yourself from a Debian WSL terminal when you are ready:

```bash
cd /mnt/c/Users/User/cyberwatch
bash scripts/host_install_smoke.sh --yes
```

The wrapper refuses to proceed without `--yes`, uses the test DSN by default,
sets `CYBERWATCH_APPLY_SCHEMA=1`, keeps destructive settings disabled, and logs
installer output to:

```bash
/tmp/cyberwatch-install.log
```

To use a different database, set `CYBERWATCH_PG_DSN` before running the wrapper.
