# Build and run from this repository

`main` is the maintained development branch. Published binaries belong on the
[GitHub releases page](https://github.com/jmontp/rtplot/releases); local builds
belong in the ignored `dist/` directory of this checkout.

## Windows

From the repository root, using Python 3.9–3.12:

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File packaging/build-windows.ps1
packaging\start-server.cmd
```

Pass `-Python C:\path\to\python.exe` to select the interpreter when building.
The script builds **committed HEAD**, creates an isolated environment under
`.build/windows/`, and writes `dist/rtplot-server.exe` plus
`dist/build-provenance.json` with the commit, executable hash, and dependencies.
Uncommitted changes must be committed before they appear in the executable.
Build caches and executable extraction stay under `.build/` on the repository's
drive. These generated files are not committed.

Use `packaging/start-server.cmd` as the stable launcher. Close the existing
server before starting its replacement: the running process keeps serving its
loaded version and holds the HTTP/ZMQ ports. A browser refresh cannot replace
that process. Restart the server between hardware sessions, with torque off.

## Other platforms and release builds

The shared PyInstaller definition is `packaging/rtplot-server.spec`. From an
environment with `.[browser]` and `pyinstaller` installed:

```sh
python -m PyInstaller packaging/rtplot-server.spec --noconfirm
```

`.github/workflows/build-binaries.yml` builds the same specification for all
three platforms. Manual dispatch produces workflow artifacts; version tags
attach binaries to a GitHub release.
