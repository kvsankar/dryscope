# Repository Guidance

- Use `uv` for Python-related commands in this repository.
- Prefer `uv run python` over calling `python` or `python3` directly.
- Prefer `uv run pytest` for tests and `uv run dryscope ...` for local CLI checks.
- Keep generated caches, cloned benchmark repositories, and temporary scan outputs outside the repository tree.
