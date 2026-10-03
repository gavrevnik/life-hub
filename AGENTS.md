# Repository instructions

When this checkout is inside `life-stack`, first read the shared [workspace instructions](../AGENTS.md) if they have not already been loaded. This file supplies project-specific overrides. If the shared file is absent in a standalone clone, continue with this file.

- Communicate with the user in Russian unless they request another language.
- The canonical repository is https://github.com/gavrevnik/life-hub.
- The default branch is `master`.
- Keep the hub dependency-free: standard-library Python and vanilla HTML/CSS/JavaScript.
- Treat `registry.json` as the source of truth for local services.
- Launch only registry-declared applications. Never execute request-provided commands or paths.
- Keep the HTTP server bound to `127.0.0.1` and preserve Host/Origin validation.
- Update `README.md` when registry fields, setup, or launcher behavior changes.
- Run `python3 -m unittest discover -s tests` and `python3 -m compileall app` before handing off changes.

## Database backup option

- For backup or restore requests, use the repository-owned [life-stack-backup skill](../life-stack-backups/skills/life-stack-backup/SKILL.md), including its restore reference when replacing live data. It delegates to the existing archive scripts; do not implement a separate backup mechanism in the hub.
- The workspace has a private manual archive: [life-stack-backups](https://github.com/gavrevnik/life-stack-backups). Read `../life-stack-backups/README.md` and its `AGENTS.md` before operating it. Its `config.json` lists databases; `scripts/snapshot.py` creates verified SQL dumps and JSON metadata, commits and pushes, and retains only three complete snapshot commits through guarded history rotation. Run only on the user's request; no timer, startup hook or Life Hub server integration.
- **When developing/registering a new service with a database, adding another database, or changing its path, remind the user to include/update it in `../life-stack-backups/config.json`.** This also applies to services intentionally excluded from the Life Hub panel. Check actual data paths and sensitive fields; do not silently upload newly discovered data. Additional SQLite databases need config entries; another database engine needs a tested adapter.
- `scripts/restore.py` lists retained snapshots and restores selected databases into a new directory with verification. It does not overwrite live data; applying a restore requires stopping the affected services and preserving current databases and WAL/SHM files. Archive history rotation must never be applied to Life Hub or other application repositories.
