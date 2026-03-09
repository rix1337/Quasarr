# Coding Style

Target Python 3.12+ and follow the conventions already used in `quasarr/`.

## Naming

- Use `snake_case` for modules, functions, variables, and test methods.
- Use `PascalCase` for classes.
- Match the existing short source-module naming scheme for hostname integrations.

## Layout

Use 4-space indentation and keep modules focused on one responsibility. Place shared helpers in the existing `helpers/` packages instead of duplicating logic across sources or providers.

## Tooling

Ruff is the enforced linting tool and also manages import sorting for first-party modules under `quasarr`:

```bash
uv run ruff check .
```

Before opening a PR, run:

```bash
uv run python -X utf8 pre-commit.py
```

Keep changes small, readable, and consistent with the surrounding code instead of introducing a separate style in one file.
