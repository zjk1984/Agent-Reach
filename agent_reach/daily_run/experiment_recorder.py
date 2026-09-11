# -*- coding: utf-8
"""Unified experiment recorder — link run manifests, harness refines, hyperopt trials."""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional
from uuid import uuid4


def experiment_recorder_cfg(settings: Optional[dict[str, Any]] = None) -> dict[str, Any]:
    block = dict((settings or {}).get("experiment_recorder") or {})
    harness = dict((settings or {}).get("harness") or {})
    study = dict(harness.get("study_registry") or {})
    jobs = block.get("jobs") or study.get("jobs") or [
        "optimize",
        "backtest",
        "hyperopt_lite",
        "close",
        "weekly",
        "intraday",
    ]
    if isinstance(jobs, str):
        jobs = [j.strip() for j in jobs.split(",") if j.strip()]
    return {
        "enabled": block.get("enabled", True) is not False,
        "max_entries": max(20, int(block.get("max_entries") or study.get("max_entries") or 200)),
        "jobs": set(str(j) for j in jobs),
        "attach_to_manifest": block.get("attach_to_manifest", True) is not False,
    }


def experiments_dir(settings: Optional[dict[str, Any]] = None) -> Path:
    block = dict((settings or {}).get("experiment_recorder") or {})
    raw = str(block.get("dir") or "").strip()
    if raw:
        path = Path(raw.replace("~", str(Path.home())))
    else:
        path = Path.home() / ".agent-reach" / "daily_run" / "experiments"
    path.mkdir(parents=True, exist_ok=True)
    return path


def _registry_path(settings: Optional[dict[str, Any]] = None) -> Path:
    return experiments_dir(settings) / "registry.json"


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def load_experiment_registry(*, settings: Optional[dict[str, Any]] = None) -> dict[str, Any]:
    path = _registry_path(settings)
    if not path.exists():
        return {"schema": 1, "experiments": []}
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return {"schema": 1, "experiments": []}
    if not isinstance(data, dict):
        return {"schema": 1, "experiments": []}
    data.setdefault("schema", 1)
    data.setdefault("experiments", [])
    return data


def save_experiment_registry(data: dict[str, Any], *, settings: Optional[dict[str, Any]] = None) -> Path:
    path = _registry_path(settings)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return path


def new_experiment_id(*, prefix: str = "exp") -> str:
    return f"{prefix}_{uuid4().hex[:10]}"


def record_experiment(
    *,
    job: str,
    params: Optional[dict[str, Any]] = None,
    metrics: Optional[dict[str, Any]] = None,
    links: Optional[dict[str, Any]] = None,
    experiment_id: Optional[str] = None,
    settings: Optional[dict[str, Any]] = None,
) -> Optional[dict[str, Any]]:
    cfg = experiment_recorder_cfg(settings)
    if not cfg["enabled"] or job not in cfg["jobs"]:
        return None

    from agent_reach.daily_run.harness_git import detect_git_branch

    exp_id = experiment_id or new_experiment_id()
    entry = {
        "experiment_id": exp_id,
        "job": job,
        "at": _now_iso(),
        "git_branch": detect_git_branch(),
        "params": dict(params or {}),
        "metrics": dict(metrics or {}),
        "links": dict(links or {}),
    }
    data = load_experiment_registry(settings=settings)
    exps = list(data.get("experiments") or [])
    exps.append(entry)
    data["experiments"] = exps[-cfg["max_entries"] :]
    data["updated_at"] = _now_iso()
    save_experiment_registry(data, settings=settings)
    return entry


def attach_experiment_to_manifest_payload(
    payload: dict[str, Any],
    *,
    job: str,
    settings: Optional[dict[str, Any]] = None,
    metrics: Optional[dict[str, Any]] = None,
    links: Optional[dict[str, Any]] = None,
) -> dict[str, Any]:
    cfg = experiment_recorder_cfg(settings)
    if not cfg["enabled"] or not cfg["attach_to_manifest"]:
        return payload
    existing = payload.get("experiment_id")
    entry = record_experiment(
        job=job,
        experiment_id=str(existing) if existing else None,
        metrics=metrics,
        links=links,
        settings=settings,
    )
    if entry:
        payload = dict(payload)
        payload["experiment_id"] = entry["experiment_id"]
        payload["experiment_at"] = entry["at"]
    return payload


def record_harness_refinement(
    refine: dict[str, Any],
    *,
    job: str,
    settings: Optional[dict[str, Any]] = None,
) -> Optional[dict[str, Any]]:
    if refine.get("skipped"):
        return None
    return record_experiment(
        job=job,
        params={"refinement_id": refine.get("refinement_id"), "changes": refine.get("changes")},
        metrics={"changes": refine.get("changes")},
        links={"state_path": refine.get("state_path"), "snapshot_path": refine.get("snapshot_path")},
        settings=settings,
    )


def record_hyperopt_experiment(
    result: dict[str, Any],
    *,
    settings: Optional[dict[str, Any]] = None,
) -> Optional[dict[str, Any]]:
    if result.get("skipped"):
        return None
    entry = record_experiment(
        job="hyperopt_lite",
        params=dict(result.get("optimal") or {}),
        metrics={
            "loss": result.get("loss"),
            "planner": result.get("planner"),
            "trials": result.get("trials"),
        },
        settings=settings,
    )
    if entry:
        try:
            from agent_reach.daily_run.harness_study_registry import register_study

            register_study(
                "hyperopt_lite",
                {
                    "objective": "hyperopt_lite_loss",
                    "best_score": result.get("loss"),
                    "trials": result.get("trials"),
                    "best_params": result.get("optimal") or {},
                    "metrics": {"loss": result.get("loss")},
                },
                settings=settings,
                refinement_id=str(entry.get("experiment_id") or ""),
            )
        except Exception:
            pass
    return entry


def summarize_experiments_for_week(
    *,
    week_start: str,
    week_end: str,
    settings: Optional[dict[str, Any]] = None,
) -> dict[str, Any]:
    from agent_reach.daily_run.harness_weekly_narrative import _parse_iso_day

    start = _parse_iso_day(week_start)
    end = _parse_iso_day(week_end)
    rows: list[dict[str, Any]] = []
    for row in load_experiment_registry(settings=settings).get("experiments") or []:
        day = _parse_iso_day(str(row.get("at") or ""))
        if start and end and day is not None and (day < start or day > end):
            continue
        rows.append(row)
    by_job: dict[str, int] = {}
    for row in rows:
        j = str(row.get("job") or "?")
        by_job[j] = by_job.get(j, 0) + 1
    return {"count": len(rows), "by_job": by_job, "experiments": rows[-20:]}
