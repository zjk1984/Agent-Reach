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
- **Daily-run scheduling** uses **local Linux cron** (not GitHub Actions schedule). One-time setup:
  `bash scripts/daily-run-local-setup.sh` then `python3 -m agent_reach.cli daily-run schedule install`.
  Logs: `~/.agent-reach/daily_run/logs/cron-YYYY-MM-DD.log`. GHA workflow is manual-only (`workflow_dispatch`).
- **Hot news (60s API)**: daily-run macro collection pulls multi-platform hot topics via
  [60s](https://github.com/vikiboss/60s). Auto-deploy (native, no Docker):
  `python3 -m agent_reach.cli daily-run hot-news install` — requires Node.js 22.6+, git, npm.
  Optional Docker: `--mode docker`. Configure `hot_news.base_urls` in settings (default
  `http://127.0.0.1:8787` then `https://60s.viki.moe`).
- **Kronos (Sunday forecast blend + close-day technical)**: `kronos.enabled=true` in
  `~/.agent-reach/daily_run_settings.json` (this machine's user override, not the repo default,
  which stays `false`) with `tokenizer_model`/`predictor_model` pointing at **local ModelScope**
  snapshot dirs under `~/.agent-reach/models/modelscope/...` — `huggingface.co` and `github.com`
  are **not reachable** from this box's network (only `pypi.org`/`hf-mirror.com` are), so
  ModelScope + local paths is the only viable model source here; don't try to `git clone` from
  GitHub or download from the bare HF Hub without the `hf-mirror.com` mirror.
  `agent-reach[daily-run-kronos]` (torch CPU wheel + safetensors/huggingface_hub/einops) is
  `pip install --break-system-packages`-ed into `~/.local` on this box (not part of the repo's
  `dev` extra, since it's a large optional dependency); if a fresh session reports
  `torch`/`huggingface_hub` missing via `is_kronos_runtime_available()`, reinstall with:
  `python3 -m pip install --break-system-packages --index-url https://download.pytorch.org/whl/cpu
  torch --extra-index-url https://pypi.org/simple safetensors huggingface_hub einops tqdm`.
  `kronos_predictor.py` sets `KMP_DUPLICATE_LIB_OK=TRUE`/`OMP_NUM_THREADS=1`/`MKL_NUM_THREADS=1`
  at import time (and `scripts/daily-run-local-cron.sh` sets the same before Python starts) to
  avoid a rare torch-MKL/numpy-MKL segfault race observed when both run in one process; don't
  remove these when touching that file/script.
