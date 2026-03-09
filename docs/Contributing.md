# Contributing

Keep commits focused and easy to review.

## Commit Messages

Recent history favors short, imperative subjects such as:

- `Fix Windows build issue`
- `Demote NK redirect resolution noise to debug`
- `chore: upgraded dependencies`

Keep the subject short enough to scan quickly, but broad enough to summarize the actual change. Do not undersell a large or multi-file change with a subject that only names one small part of it.

When a commit touches several related areas, use a subject that captures the shared theme and add a short body only when the subject alone is not enough.

When you use a body, list only the main changes that define the commit. Do not pad the message with supporting details such as follow-up links, ignore-rule tweaks, log handling, or other incidental edits unless those details are the actual point of the commit.

Use `chore:` for maintenance-only changes, but still describe the main maintenance work. Keep feature or bug-fix commits specific to one concern while naming the main behavior, workflow, or surface area affected.

## Pull Requests

Pull requests should describe the user-visible change, call out any config or hostname impact, and avoid mixing unrelated cleanup with functional work. For UI or integration changes, include proof of behavior such as screenshots, logs, or a brief reproduction example.

The project README asks contributors to coordinate on Discord before starting large new features to avoid duplicate work. For development environment details, also see the root `CONTRIBUTING.md` and `docs/Development.md`.
