# CLAUDE.md

<!-- claude-insights:start -->
## Working with Claude

These working agreements come from a `/insights` analysis of past sessions. Keep them in mind on every task in this repo.

- When pre-commit or pre-push hooks fail, fix the underlying issues (line length, trailing whitespace, lint errors) properly. Do NOT skip hooks, amend silently, or work around them. Never run `git init`, rewrite history (rebase, force push), or skip flaky tests without explicit permission.
- When asked to fix a problem, diagnose the root cause before proposing a fix. Do not jump to surface-level changes (e.g., flipping a port without understanding the networking, attributing a CSS bug to line-height without investigating).
- If two approaches have failed for the same problem, stop and present options to the user instead of trying a third. Don't thrash.
- Never fabricate documentation content. If you don't know what a doc actually says, read the file first.
<!-- claude-insights:end -->
