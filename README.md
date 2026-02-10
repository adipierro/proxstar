Proxstar
===========

## WIP. fork of a project by CSH of rit.edu.

- Proxmox SDNs instead of STARRS. VMnet firewall security groups applied per-pool (per-user)
- Session limits for users. VMs are shut down after timer ends.
- LDAP removed. Roles based on OIDC claims.
- dockerized

Full disclosure: mostly vibe-coded for a PoC. Will be refactored once applicability confirmed.

===========

[![Python 3.13](https://img.shields.io/badge/python-3.13-blue.svg)](https://www.python.org/downloads/release/python-3130/)
[![Proxstar](https://github.com/ComputerScienceHouse/proxstar/actions/workflows/python-app.yml/badge.svg)](https://github.com/ComputerScienceHouse/proxstar/actions/workflows/python-app.yml)

Proxstar is a proxmox VM web management tool used by [Rochester Institute of Technology](https://rit.edu/)'s [Computer Science House](https://csh.rit.edu).

## Overview

Written using [Python](http://nodejs.org), [Flask](https://npmjs.com).

Proxstar removes the need for CSH members to have direct access to the proxmox web interface.

Proxstar is also used to enforce proxmox resource limits automagically.

It is available to house members at [proxstar.csh.rit.edu](https://proxstar.csh.rit.edu) behind PYOIDC authentication.

## Contributing

Check out `HACKING/` for more info.

## Docker

1. Copy `docker/.env.example` to `.env` and fill in real values.
2. Run `docker compose up --build`.

This starts:
- `web` on port `8080`
- `websockify` on port `8081` (for noVNC console)
- `worker` (RQ worker)
- `scheduler` (RQ scheduler)
- `db` (Postgres)
- `redis`

## Tests

1. Install dev deps: `pip install -r requirements-dev.txt`
2. Run: `pytest`

## Local Auth (No OIDC)

For local development only, you can bypass OIDC:

- Set `PROXSTAR_DISABLE_AUTH=true`
- Optionally set `PROXSTAR_LOCAL_USER=yourname`
- Optionally set `PROXSTAR_LOCAL_GROUPS=admin,active`

## OIDC Groups (No LDAP)

The app now uses OIDC groups for authorization:

- `PROXSTAR_OIDC_GROUPS_CLAIM` (default `groups`)
- `PROXSTAR_OIDC_ADMIN_GROUPS` (comma-separated)
- `PROXSTAR_OIDC_ACTIVE_GROUPS` (comma-separated)
- `PROXSTAR_OIDC_STUDENT_GROUPS` (comma-separated)

If both `PROXSTAR_OIDC_ACTIVE_GROUPS` and `PROXSTAR_OIDC_STUDENT_GROUPS` are empty,
any authenticated user is treated as active.

## VNC Console (Docker)

The console uses `websockify` + noVNC:

1. Docker builds download noVNC into `proxstar/static/noVNC/` (override via `--build-arg NOVNC_VERSION=...`).
2. Expose `PROXSTAR_WEBSOCKIFY_PORT` from the `web` container.
3. Set `PROXSTAR_VNC_HOST`/`PROXSTAR_VNC_PORT` to the public host/port the browser can reach.

## Questions/Concerns

Please file an [Issue](https://github.com/adipierro/proxstar/issues/new) on this repository.
