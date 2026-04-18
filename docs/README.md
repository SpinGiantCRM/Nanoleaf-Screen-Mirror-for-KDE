# Documentation index

This index is the documentation entrypoint for contributors and maintainers.
If you are not sure where to read first, follow one of the role-based paths below.

## Start here by role

### I am an end user
1. Root `README.md` (project overview + primary install flow).
2. `INSTALL_ARCH.md` (recommended Arch/CachyOS installation).
3. `HARDWARE_SETUP.md` (real USB permission setup).
4. `TROUBLESHOOTING.md` (if something fails).

### I am a contributor
1. `../CONTRIBUTING.md` (development workflow and expectations).
2. `REPOSITORY_MAP.md` (what each directory/file family is for).
3. `TECHNICAL_DESIGN.md` (architecture and runtime pipeline).
4. `SMOKE_TEST.md` (manual validation basics).

### I am preparing a release
1. `RELEASE_CHECKLIST.md`
2. `RC_TEST_MATRIX.md`
3. `RELEASE_TOOLCHAIN.md`
4. `CHANGELOG.md`

## Full docs catalog

| Document | Purpose |
| --- | --- |
| `README.md` | This docs index and navigation map. |
| `REPOSITORY_MAP.md` | Comprehensive repo structure and ownership map. |
| `INSTALL_ARCH.md` | Arch/CachyOS install instructions and artifact verification. |
| `HARDWARE_SETUP.md` | Nanoleaf USB permission and udev setup. |
| `TROUBLESHOOTING.md` | User-facing diagnosis and remediation guidance. |
| `SMOKE_TEST.md` | Smoke test procedure and expected pass/fail interpretation. |
| `TECHNICAL_DESIGN.md` | Architecture intent, data flow, and implementation status. |
| `DRIVER_INTEGRATION_PLAN.md` | Device-driver integration plan/history. |
| `RELEASE_CHECKLIST.md` | Release gate checklist used by maintainers. |
| `RC_TEST_MATRIX.md` | Release candidate test matrix and sign-off expectations. |
| `RELEASE_TOOLCHAIN.md` | Build/release tooling references. |
| `CHANGELOG.md` | Release history and unreleased notes. |
| `nanoleaf-kde-sync.desktop` | Desktop entry template/reference. |
| `requirements.txt` | Runtime dependency pinning for source installs. |
| `requirements-test.txt` | Minimal CI/test-only dependency set. |

## Documentation maintenance rules

- Update docs in the same PR as behavior changes.
- Prefer linking to a single source-of-truth document instead of duplicating long instructions.
- If you remove or relocate files, update this index and `REPOSITORY_MAP.md` in the same commit.
