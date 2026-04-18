# Contributing

Thanks for contributing to Nanoleaf Screen Mirror for KDE.

## Getting started

1. Fork the repository and create a feature branch.
2. Install dependencies:

```bash
pip install -e .[test]
```

3. Run tests:

```bash
pytest -q
```

## Reporting bugs

When opening an issue, include:

- exact version or commit
- installation method (package, pip, or source)
- output from `nanoleaf-kde-sync-doctor`
- output from `nanoleaf-kde-sync-smoke-test`
- clear reproduction steps

If the issue only happens with a real device, include `nanoleaf-kde-sync-doctor --device` output.

## Pull requests

Please keep pull requests focused and easy to review.

- Keep each PR scoped to one main change.
- Update documentation when behavior changes.
- Add or update tests when applicable.
- Run the test suite before opening the PR.

## Documentation

If your change affects installation, configuration, commands, or runtime behavior, update the relevant documentation in the same pull request.
