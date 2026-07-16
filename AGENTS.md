# AGENTS.md

## Cursor Cloud specific instructions

Agent Reach is a Python 3.10+ CLI + library (installer / doctor / config tool for AI-agent
internet access, plus a `daily-run` stock skill). The update script already runs
`pip install -c constraints.txt -e '.[dev]'`, so dependencies are present at session start.

Non-obvious environment notes:

- Use `python3` — there is no `python` on PATH.
- Console scripts install to `~/.local/bin`, which is NOT on PATH. Do not rely on the bare
  `agent-reach`, `ruff`, or `pytest` commands. Instead run:
  - CLI: `python3 -m agent_reach.cli <command>` (e.g. `python3 -m agent_reach.cli doctor`)
  - Tests: `python3 -m pytest -q`
  - Lint: `python3 -m ruff check .`
- CI (`.github/workflows/pytest.yml`) runs only `pytest -q` (+ a wheel-gate job). It does NOT
  run ruff. The repo currently has pre-existing ruff lint errors (mostly `I001`/`F401`); leave
  them unless a task is specifically about lint.
- `agent-reach doctor` may report `yt-dlp` as "not installed" even though it is pip-installed,
  because doctor probes PATH and `~/.local/bin` is not on PATH. This is a PATH artifact, not a
  missing dependency.
- CLAUDE.md documents older `read`/`search` subcommands that no longer exist. The real
  subcommands are shown by `python3 -m agent_reach.cli -h` (setup, install, configure, notify,
  daily-run, doctor, uninstall, skill, format, transcribe, check-update, watch, version).
- Network- and credential-free smoke test of core logic (good "hello world"):
  `python3 -m agent_reach.cli daily-run sample > snap.json` then
  `python3 -m agent_reach.cli daily-run evaluate --input snap.json`.
- Many channels (Twitter, Reddit, XHS, Exa search, transcription, Feishu) need API keys /
  cookies (see `.env.example`) and outbound network; they will show as unavailable in doctor
  without configuration and are optional for local development.
