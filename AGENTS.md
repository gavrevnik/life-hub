# Repository instructions

- Communicate with the user in Russian unless they request another language.
- The canonical repository is https://github.com/gavrevnik/life-hub.
- The default branch is `master`.
- Keep the hub dependency-free: standard-library Python and vanilla HTML/CSS/JavaScript.
- Treat `registry.json` as the source of truth for local services.
- Launch only registry-declared applications. Never execute request-provided commands or paths.
- Keep the HTTP server bound to `127.0.0.1` and preserve Host/Origin validation.
- Update `README.md` when registry fields, setup, or launcher behavior changes.
- Run `python3 -m unittest discover -s tests` and `python3 -m compileall app` before handing off changes.
