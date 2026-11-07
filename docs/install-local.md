# How to install Domus locally

This guide gets Domus running on one computer, loads the sample home so you have
something to click through, and shows how to back up, restore, and check your data. The
last section is a checklist for testing upgrades.

It describes what is on `main` today (v0.1 in progress). Notes marked **Coming in v0.1**
mark where features that are still being built will be documented.

> **Before v0.3, upgrades may not keep your data.** The database schema and backup format
> can still change between versions with no upgrade path, so a newer Domus may not open
> an older data folder or restore an older backup. Treat v0.1 and v0.2 as trial versions
> and don't rely on them for data you can't enter again.

## Contents

1. [Prerequisites](#prerequisites)
2. [Install with uv](#install-with-uv)
3. [Install with Docker](#install-with-docker)
4. [First run: create the first Admin](#first-run-create-the-first-admin)
5. [Load the sample home](#load-the-sample-home)
6. [Connect Home Assistant (optional)](#connect-home-assistant-optional)
7. [Where your data lives](#where-your-data-lives)
8. [Back up, verify, and restore](#back-up-verify-and-restore)
9. [Upgrade test checklist](#upgrade-test-checklist)
10. [Settings](#settings)
11. [Troubleshooting](#troubleshooting)

## Prerequisites

Pick one way to run Domus.

| To run with | You need |
| :-- | :-- |
| uv (from a source checkout) | [git](https://git-scm.com/), [uv](https://docs.astral.sh/uv/getting-started/installation/) (it installs Python 3.14 for you), and [Node.js](https://nodejs.org/) 22.12 or later to build the web interface |
| Docker | [Docker Engine](https://docs.docker.com/engine/install/) or Docker Desktop with Compose v2, and git |

Domus works fully offline once it is installed. Nothing is loaded from the internet at
run time, and Home Assistant is never required.

Domus isn't published to PyPI or a container registry yet, so both ways start from a
checkout of the repository:

```sh
git clone https://github.com/punderthings/domus.git
cd domus
```

## Install with uv

From the repository root:

```sh
# 1. Build the web interface (writes src/domus/static/).
cd src/frontend
npm ci --ignore-scripts
npm run build
cd ../..

# 2. Install Domus and its dependencies into .venv.
uv sync

# 3. Start the server.
uv run domus serve
```

Open <http://127.0.0.1:8000> in a browser. `domus serve` creates or migrates the database
on start, so there is no separate setup command. It listens on `127.0.0.1` (this computer
only) unless you pass `--host`; see [Settings](#settings) before you do.

If you skip step 1, the API still works (try <http://127.0.0.1:8000/api/v1/docs>), but
`/` returns 404 because there is no web interface to serve.

Stop the server with Ctrl+C. Every other `domus` command (backups, restores, imports)
runs from the same folder with `uv run domus ...`. Run `uv run domus --help` to list them.

## Install with Docker

The image holds the server, the `domus` command, the built web interface, and the
sample dataset. Your data lives in a Docker volume mounted at `/data`. From the
repository root:

```sh
docker compose -f deploy/compose.yaml up -d --build
```

Open <http://127.0.0.1:8000>. The Compose file publishes the port on `127.0.0.1` only;
to reach Domus from other devices, see [HTTPS for other devices](#https-for-other-devices).

Useful commands (run from the repository root):

```sh
docker compose -f deploy/compose.yaml ps          # status, including the health check
docker compose -f deploy/compose.yaml logs -f     # server logs
docker compose -f deploy/compose.yaml stop        # stop, keeping your data
docker compose -f deploy/compose.yaml start       # start again
```

To run a `domus` command against the same data, use `exec` while the server is running,
or `run --rm` while it is stopped (restores need it stopped):

```sh
docker compose -f deploy/compose.yaml exec domus domus --help
docker compose -f deploy/compose.yaml run --rm domus domus --help
```

To shorten these, run `export COMPOSE_FILE=deploy/compose.yaml` once in your shell; then
`docker compose up -d` and the rest work without `-f`.

Without Compose, build and run the image directly:

```sh
docker build -f deploy/Dockerfile -t domus:local .
docker run -d --name domus -p 127.0.0.1:8000:8000 -v domus-data:/data domus:local
```

The container runs as an unprivileged user (uid 10001). If you mount a host folder at
`/data` instead of a named volume, make that user its owner first
(`sudo chown 10001:10001 ./data`).

### HTTPS for other devices

Domus marks its login cookie `Secure`, so browsers send it only over HTTPS, or over
plain http to `localhost` or `127.0.0.1`. To use Domus from a phone or another computer,
put HTTPS in front of it. The Compose file has an optional Caddy reverse proxy for that:

```sh
DOMUS_HOSTNAME=domus.home.arpa docker compose -f deploy/compose.yaml --profile https up -d
```

Point that name at the Docker host (in your router's DNS or each device's hosts file).
Caddy issues a certificate from its own local certificate authority, so each device
needs to trust Caddy's root certificate once; see
[Caddy's local HTTPS docs](https://caddyserver.com/docs/automatic-https#local-https).
The details are in `deploy/Caddyfile`.

On a network you trust, you can instead set `DOMUS_COOKIE_SECURE=false` and publish
port 8000 on all interfaces. Passwords and session cookies then travel unencrypted, so
don't do this on shared or public networks.

## First run: create the first Admin

The first time you open Domus, it shows **Create account**. Fill in:

- **Property name**: your home, for example "Maple Street". Domus creates the property
  and its main building, named "House". (If you loaded the sample home first, this name
  isn't used; see below.)
- **Your name**, **Email**, and a **Password** of at least 12 characters.

This account is the property's **Admin**. Setup runs only once: when the first account
exists, the page shows the normal sign-in form. Add other people (Maintainer, Resident,
Guest) later as members of the property.

To check from the command line whether setup is still needed:

```sh
curl http://127.0.0.1:8000/api/v1/auth/setup     # {"needs_setup":true} on a new install
curl http://127.0.0.1:8000/api/v1/health         # {"status":"ok","version":"..."}
```

## Load the sample home

The sample home in [`examples/sample-home/`](https://github.com/punderthings/domus/tree/main/examples/sample-home) is a
small fictional property: one house, two floors, four rooms, nine devices, five
maintenance tasks (two already overdue), tags, and access rules. Use it to try Domus or
to test changes by hand.

There are two ways to load it. Both give you the same data.

### From the web interface

Sign in as an Admin. While your property has no rooms yet (as it is right after setup),
the Overview shows **Try Domus with sample data**. Select **Load sample data**: Domus adds
Sample Home as a second property, makes you its Admin, and switches to it. Your own
property isn't changed. To switch between the two, open the account menu (the round
button with your initial, top right) and pick a property.

Sample Home can be loaded this way once per install. When it already has members, the
card no longer appears and another Admin can't claim it.

The web interface finds the dataset in `examples/sample-home/` of a source checkout,
and in `/opt/domus/examples/sample-home` in the Docker image. An install without it,
such as one installed from a wheel, doesn't show the card; set `DOMUS_SAMPLE_DATA_DIR`
to a copy of the folder to enable it.

### From the command line, into a blank instance

For manual testing, you can also load it **before** you create the first Admin. Setup
then adds the new Admin to Sample Home instead of creating an empty property, so you
sign in straight to a populated home with no second property.

With uv, from the repository root (the server can be stopped or never started):

```sh
export DOMUS_DATA_DIR="$PWD/.domus-test"     # optional: keep test data apart from real data
uv run domus restore examples/sample-home --merge --dry-run   # preview: 62 rows inserted
uv run domus restore examples/sample-home --merge             # import
uv run domus serve
```

With Docker, the dataset is in the image at `/opt/domus/examples/sample-home`:

```sh
docker compose -f deploy/compose.yaml stop
docker compose -f deploy/compose.yaml run --rm domus domus restore /opt/domus/examples/sample-home --merge
docker compose -f deploy/compose.yaml start
```

Then open Domus and create your account. Any property name works; it is ignored because
a property already exists. The import reports two warnings, `ignoring unexpected file
README.md` and `manifest lists no file hashes`. Both are expected for this dataset.

Running the same command on an install that already has an Admin adds Sample Home with
no members, because the import never touches accounts. An Admin can then claim it with
**Load sample data** in the web interface.

The import upserts by id: running it again changes nothing, and edits you made to sample
records in the app are kept if they are newer.

### What you should see

- **Overview**: Sample Home at "123 Example Lane, Springfield", with the smoke detector
  test and the hose valve task listed as overdue, and House with Main Floor (Kitchen,
  Living Room, Primary Bedroom) and Basement (Utility Room).
- **Devices**: nine devices, with the Gas Furnace marked **Critical** and the Wi-Fi,
  light, and console devices tagged `smart`.

To start over, stop the server and delete the data folder (here `.domus-test`; for Docker,
`docker compose -f deploy/compose.yaml down -v` deletes the volume and **all data in it**).

## Connect Home Assistant (optional)

Domus works on its own; Home Assistant is optional. Devices already have fields for
Home Assistant device and entity ids (the sample Living Room Light Switch has them), and
you can fill those in by hand today.

> **Coming in v0.1:** importing areas and devices from Home Assistant. This section will
> cover creating a long-lived access token in Home Assistant, giving it to Domus, and
> running the import.

## Where your data lives

Everything is in one data folder:

| Run with | Data folder |
| :-- | :-- |
| uv | `~/.local/share/domus/` (on Windows, `%USERPROFILE%\.local\share\domus\`), or `DOMUS_DATA_DIR` if set |
| Docker | `/data` in the container, stored in the `domus-data` volume (`domus_domus-data` when started with Compose) |

Inside it:

| Path | What it holds |
| :-- | :-- |
| `domus.sqlite` | The database. `-wal` and `-shm` files next to it are part of it while the server runs. |
| `blobs/` | Uploaded files (floor plans, wall photos, manuals), named by SHA-256 hash; created with the first upload |
| `backups/` | Backups made with `domus backup create`, and the automatic safety copies made before each restore |

With the server stopped, copying the whole data folder is also a valid backup. Backups
contain password hashes and everything about your home, so keep them somewhere private.

Uploaded images are re-encoded when they are saved, which removes EXIF data such as GPS
location. They are stored in `blobs/` and included in backups like everything else.

> **Coming in v0.1:** search.

## Back up, verify, and restore

Backups are `.hiotbak` files: a zip with a manifest, a consistent copy of the database,
one JSONL file per table, and the blobs. You can open them with any zip tool.

### Make a backup

The server can keep running.

```sh
uv run domus backup create
# Backup written to ~/.local/share/domus/backups/domus-20261106T230337Z.hiotbak
```

Use `--output PATH` to write it somewhere else, such as a USB drive. With Docker:

```sh
docker compose -f deploy/compose.yaml exec domus domus backup create
docker compose -f deploy/compose.yaml cp domus:/data/backups ./domus-backups   # copy them out
```

A backup in the data folder doesn't survive losing the disk, so copy backups to another
place as well.

### Verify a backup

```sh
uv run domus backup verify path/to/domus-20261106T230337Z.hiotbak
# path/to/domus-20261106T230337Z.hiotbak is OK (65 rows).
```

Verify checks the manifest, every file's SHA-256, the row counts, the database copy, and
the blobs. It changes nothing and exits non-zero on any error, so you can script it. A
backup made by a newer Domus than the one you run fails with a message that its schema
is newer than this app.

### Restore a backup

**Stop the server first.** A full restore replaces all current data, accounts included.

```sh
uv run domus restore --dry-run path/to/backup.hiotbak   # what would change; saves nothing
uv run domus restore path/to/backup.hiotbak             # asks for confirmation; -y skips it
```

Before it replaces anything, restore saves the current database to
`backups/domus-pre-restore-<time>.hiotbak` and prints that path. To undo the restore,
restore that file. If the restore fails partway, the current data is left as it was.

With Docker, copy the backup into the volume, then restore with the server stopped:

```sh
docker compose -f deploy/compose.yaml stop
docker compose -f deploy/compose.yaml cp ./domus-backups/backup.hiotbak domus:/data/backups/
docker compose -f deploy/compose.yaml run --rm domus domus restore -y /data/backups/backup.hiotbak
docker compose -f deploy/compose.yaml start
```

`restore --merge` adds a backup's records into the current data instead (records match
by id; the newer `updated_at` wins) and never changes accounts. Use it to combine data,
not to recover from a problem.

### Export as plain files

`domus export DIR` writes every record, except accounts and sessions, as
`manifest.json` plus `data/<table>.jsonl` into a new or empty directory. It is for
reading, comparing, or moving data, not a replacement for a backup. The upgrade test
below uses it to compare data.

## Upgrade test checklist

Maintainers: run this before each release, and for any pull request that changes the
data model or the backup format. It checks that data survives an upgrade, and that a
downgrade is refused cleanly instead of losing data. The steps use uv and two checkouts,
**OLD** (for example the last release tag) and **NEW** (the branch under test), with a
scratch data folder so your own data is never touched.

> **During v0.1 and v0.2, compatibility isn't required.** Shane decided that the schema
> and backup format can change freely in these releases, with no need to upgrade older
> databases or restore older backups. Until v0.3, run this checklist to find out what
> breaks and say so in the release notes, rather than as a release gate. A failure in
> the "upgrade in place" or "restore the OLD backup" steps is then expected when the
> schema changed; the "downgrade is refused" steps still have to pass, so old versions
> never load data they can't read.

Set up once:

```sh
export T="$(mktemp -d)"                  # scratch space
git worktree add "$T/old" main           # OLD: the last release tag, or main
git worktree add "$T/new" my-branch      # NEW: the branch under test
```

Run each `domus` command from inside the checkout named in the step
(`cd "$T/old"` or `cd "$T/new"`), so that `uv run` uses that version.

**On OLD:**

- [ ] `export DOMUS_DATA_DIR="$T/data-old"`
- [ ] Load the sample home: `uv run domus restore examples/sample-home --merge`.
- [ ] Start `uv run domus serve`, create an Admin, and make a few changes by hand: edit a
      device, add one, log a maintenance event, and upload a floor plan with a device pin
      on it, so files are tested too. Stop the server.
- [ ] `uv run domus backup create --output "$T/old.hiotbak"`
- [ ] `uv run domus backup verify "$T/old.hiotbak"` reports OK.
- [ ] `uv run domus export "$T/export-old"`
- [ ] Note the version for the record: `git -C "$T/old" describe --always`.

**On NEW, upgrade in place:**

- [ ] Keep `DOMUS_DATA_DIR="$T/data-old"`. Run `uv run domus db upgrade`; it prints
      "Database is up to date." with no errors.
- [ ] `uv run domus export "$T/export-upgraded"`
- [ ] `diff -r -x manifest.json "$T/export-old" "$T/export-upgraded"` shows no changes,
      or only the changes the release notes describe (for example a new column).
- [ ] Start `uv run domus serve`, sign in with the same Admin, and spot-check the records
      you changed on OLD, including the floor plan and its pin.

**On NEW, restore the OLD backup into a fresh instance:**

- [ ] `export DOMUS_DATA_DIR="$T/data-new"` (empty)
- [ ] `uv run domus backup verify "$T/old.hiotbak"` reports OK.
- [ ] `uv run domus restore -y "$T/old.hiotbak"`
- [ ] `uv run domus export "$T/export-restored"`, then
      `diff -r -x manifest.json "$T/export-upgraded" "$T/export-restored"` shows no changes.
- [ ] Sign in with the OLD Admin's password; the account came back with the backup.
- [ ] Row counts match: `diff "$T/export-old/manifest.json" "$T/export-restored/manifest.json"`
      shows only the `created_at` line (and `app_version`/`schema_version` when they changed).

**Downgrade is refused:**

- [ ] On NEW, `uv run domus backup create --output "$T/new.hiotbak"` (with
      `DOMUS_DATA_DIR="$T/data-new"`).
- [ ] On OLD, `uv run domus backup verify "$T/new.hiotbak"`. If the schema changed between
      the two versions, it fails with "schema_version ... is newer than this app"; if it
      didn't, it reports OK.
- [ ] On OLD, with a scratch `DOMUS_DATA_DIR`, `uv run domus restore -y "$T/new.hiotbak"`
      is refused the same way when the schema changed, and leaves that data folder as it
      was.

**Docker image:**

- [ ] Build NEW with `docker compose -f deploy/compose.yaml build`, then
      `docker compose -f deploy/compose.yaml up -d` on a volume that OLD's image created.
      `docker compose -f deploy/compose.yaml ps` shows the service `healthy`, and you can
      sign in.

**Clean up:** `git worktree remove "$T/old"`, `git worktree remove "$T/new"`, and
`rm -rf "$T"`.

Record the result (versions, pass or fail, anything odd) in the release pull request.

## Settings

Domus reads settings from environment variables that start with `DOMUS_`.

| Variable | Default | What it does |
| :-- | :-- | :-- |
| `DOMUS_DATA_DIR` | `~/.local/share/domus` (`/data` in Docker) | Folder for the database, files, and backups |
| `DOMUS_DATABASE_URL` | SQLite in the data folder | Database URL. Leave unset; PostgreSQL support is experimental and not in v0.1 yet. |
| `DOMUS_COOKIE_SECURE` | `true` | Send the login cookie over HTTPS only (plain http to `localhost` and `127.0.0.1` still works). Set `false` only for plain http on a trusted network. |
| `DOMUS_SESSION_DAYS` | `14` | How long a sign-in lasts |
| `DOMUS_LOGIN_MAX_FAILURES` | `5` | Failed sign-ins allowed per window before Domus blocks more attempts |
| `DOMUS_LOGIN_WINDOW_SECONDS` | `300` | Length of that window |
| `DOMUS_BACKUP_MAX_BYTES` | `2147483648` (2 GiB) | Largest size a backup may expand to when verified or restored |
| `DOMUS_UPLOAD_MAX_BYTES` | `26214400` (25 MiB) | Largest single file upload (photos, floor plans, manuals) |
| `DOMUS_SAMPLE_DATA_DIR` | `examples/sample-home` in a source checkout (`/opt/domus/examples/sample-home` in Docker) | The sample home that **Load sample data** imports |

`domus serve` takes `--host` (default `127.0.0.1`) and `--port` (default `8000`). The
Docker image listens on `0.0.0.0` inside the container, and the Compose file publishes it
on `127.0.0.1` only.

## Troubleshooting

- **The page at `/` is "Not Found".** The web interface isn't built. Run `npm ci
  --ignore-scripts && npm run build` in `src/frontend`, then restart the server.
- **Sign-in seems to work but you're sent back to the sign-in page.** The browser dropped
  the `Secure` cookie because you used plain http on a name other than `localhost` or
  `127.0.0.1`. Use HTTPS (see [HTTPS for other devices](#https-for-other-devices)).
- **"Too many failed logins; wait".** Wait `DOMUS_LOGIN_WINDOW_SECONDS` (5 minutes by
  default), or restart the server.
- **Forgot the only Admin's password.** There is no reset command yet. Restore a backup
  made when you knew the password, or start a new data folder and `restore --merge` a
  backup into it before setup (this keeps your home's data but not the accounts).
- **Restore says the schema is newer than this app.** The backup came from a newer
  Domus. Upgrade Domus, then restore.
- **Docker container is `unhealthy`.** Check `docker compose -f deploy/compose.yaml logs`.
  A mounted host folder the container can't write to is the usual cause; see
  [Install with Docker](#install-with-docker).
