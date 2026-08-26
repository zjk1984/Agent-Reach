# -*- coding: utf-8
"""Load/save prior close MSS for morning reference."""

from __future__ import annotations

import json
from datetime import date, timedelta
from pathlib import Path
from typing import Any, Optional

from agent_reach.daily_run.run_manifest import runs_dir
from agent_reach.daily_run.snapshot_builder import _normalize_code
from agent_reach.daily_run.trade_calendar import is_trading_day, today_shanghai


def prior_close_enabled(settings: dict[str, Any]) -> bool:
    cfg = settings.get("morning_mss") or {}
    return cfg.get("use_prior_close", True) is not False


def show_prior_close_delta(settings: dict[str, Any]) -> bool:
    cfg = settings.get("morning_mss") or {}
    return cfg.get("show_delta_in_report", True) is not False


def close_baseline_path(code: str) -> Path:
    norm = _normalize_code(str(code))
    return Path.home() / ".agent-reach" / "daily_run" / "baselines" / "close" / f"{norm}.json"


def prev_trading_day(
    d: Optional[date] = None,
    *,
    settings: Optional[dict[str, Any]] = None,
) -> date:
    """Previous A-share trading day before ``d`` (default today Shanghai)."""
    cursor = (d or today_shanghai()) - timedelta(days=1)
    cfg = settings or {}
    for _ in range(15):
        ok, _ = is_trading_day(cursor, settings=cfg)
        if ok:
            return cursor
        cursor -= timedelta(days=1)
    return (d or today_shanghai()) - timedelta(days=1)


def save_close_baseline(
    *,
    snapshot: dict[str, Any],
    verify: Optional[dict[str, Any]] = None,
    code: Optional[str] = None,
    primary_code: Optional[str] = None,
) -> Optional[Path]:
    """Persist close MSS snapshot for next-morning reference."""
    norm = _normalize_code(str(code or snapshot.get("code") or ""))
    if not norm or norm == "MARKET":
        return None

    verify = verify or {}
    mss_final = verify.get("mss_current")
    if mss_final is None:
        mss_final = snapshot.get("mss_final")
    if mss_final is None:
        return None

    payload: dict[str, Any] = {
        "code": norm,
        "name": verify.get("name") or snapshot.get("name") or norm,
        "mss_final": float(mss_final),
        "mss_breakdown": snapshot.get("mss_breakdown") or {},
        "verdict": verify.get("verdict_current") or snapshot.get("verdict"),
        "as_of": snapshot.get("as_of"),
        "close_date": today_shanghai().isoformat(),
        "report_type": "close",
        "_baseline_source": "close_baseline",
    }

    out = close_baseline_path(norm)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

    try:
        from agent_reach.daily_run.storage.hooks import on_baseline

        on_baseline("close", norm, payload, source_path=str(out))
    except Exception:
        pass

    pc = _normalize_code(str(primary_code)) if primary_code else None
    if pc and norm == pc:
        legacy = Path.home() / ".agent-reach" / "daily_run" / "last_close.json"
        legacy.parent.mkdir(parents=True, exist_ok=True)
        legacy.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return out


def load_close_baseline(code: str) -> Optional[dict[str, Any]]:
    norm = _normalize_code(str(code))
    per = close_baseline_path(norm)
    try:
        from agent_reach.daily_run.storage.config import path_under_daily_run_data

        if path_under_daily_run_data(per.parent):
            from agent_reach.daily_run.settings import load_settings
            from agent_reach.daily_run.storage.readers import read_close_baseline_from_store

            db_row = read_close_baseline_from_store(norm, settings=load_settings())
            if db_row:
                return db_row
    except Exception:
        pass
    if per.exists():
        try:
            return json.loads(per.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            pass
    legacy = Path.home() / ".agent-reach" / "daily_run" / "last_close.json"
    if legacy.exists():
        try:
            data = json.loads(legacy.read_text(encoding="utf-8"))
            if _normalize_code(str(data.get("code", ""))) == norm:
                return data
        except (json.JSONDecodeError, OSError):
            pass
    return None


def _mss_from_manifest(record: dict[str, Any]) -> Optional[float]:
    payload = record.get("payload") or {}
    result = payload.get("result") or {}
    snap = result.get("snapshot") or {}
    if snap.get("mss_final") is not None:
        return float(snap["mss_final"])
    verify = result.get("verify") or {}
    if verify.get("mss_current") is not None:
        return float(verify["mss_current"])
    evaluation = result.get("evaluation") or {}
    report = evaluation.get("report") or {}
    if report.get("mss_final") is not None:
        return float(report["mss_final"])
    return None


def _code_from_manifest(record: dict[str, Any]) -> Optional[str]:
    payload = record.get("payload") or {}
    result = payload.get("result") or {}
    for block in (result.get("snapshot"), result.get("verify"), result):
        if isinstance(block, dict) and block.get("code"):
            return _normalize_code(str(block["code"]))
    sym_results = payload.get("symbol_results") or []
    if sym_results:
        first = sym_results[0]
        if isinstance(first, dict) and first.get("code"):
            return _normalize_code(str(first["code"]))
    return None


def _load_close_from_manifest(day: date, code: str) -> Optional[dict[str, Any]]:
    day_dir = runs_dir() / day.isoformat()
    if not day_dir.exists():
        return None
    norm = _normalize_code(code)
    for path in sorted(day_dir.glob("close_*.json"), reverse=True):
        try:
            record = json.loads(path.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            continue
        manifest_code = _code_from_manifest(record)
        if manifest_code and manifest_code != norm:
            continue
        mss = _mss_from_manifest(record)
        if mss is None:
            continue
        payload = record.get("payload") or {}
        result = payload.get("result") or {}
        verify = result.get("verify") or {}
        snap = result.get("snapshot") or {}
        return {
            "code": norm,
            "name": verify.get("name") or snap.get("name") or norm,
            "mss_final": mss,
            "mss_breakdown": snap.get("mss_breakdown") or {},
            "verdict": verify.get("verdict_current") or snap.get("verdict"),
            "close_date": day.isoformat(),
            "as_of": record.get("at"),
            "_baseline_source": f"manifest:{path.name}",
        }
    return None


_DAY_INTRADAY_BEST: dict[str, dict[str, dict[str, Any]]] = {}


def _intraday_best_scans_for_day(day: date) -> dict[str, dict[str, Any]]:
    """Parse intraday manifests once per day; return best scan per symbol."""
    ds = day.isoformat()
    cached = _DAY_INTRADAY_BEST.get(ds)
    if cached is not None:
        return cached

    day_dir = runs_dir() / ds
    best: dict[str, tuple[str, dict[str, Any]]] = {}
    if day_dir.exists():
        for path in sorted(day_dir.glob("intraday_*.json")):
            try:
                record = json.loads(path.read_text(encoding="utf-8"))
            except (json.JSONDecodeError, OSError):
                continue
            payload = record.get("payload") or {}
            for row in payload.get("symbol_results") or []:
                if not isinstance(row, dict):
                    continue
                norm = _normalize_code(str(row.get("code", "")))
                if not norm:
                    continue
                scan_wrap = (row.get("result") or {}).get("scan") or {}
                scan = scan_wrap.get("scan") if isinstance(scan_wrap.get("scan"), dict) else scan_wrap
                if not isinstance(scan, dict) or scan.get("mss_final") is None:
                    continue
                as_of = str(scan.get("as_of") or record.get("at") or "")
                prev = best.get(norm)
                if prev is None or as_of >= prev[0]:
                    best[norm] = (as_of, scan)

    out: dict[str, dict[str, Any]] = {}
    for norm, (as_of, scan) in best.items():
        out[norm] = {
            "code": norm,
            "name": scan.get("name") or norm,
            "mss_final": float(scan["mss_final"]),
            "mss_breakdown": scan.get("mss_breakdown") or {},
            "verdict": scan.get("verdict"),
            "close_date": ds,
            "scan_id": scan.get("scan_id"),
            "as_of": as_of or None,
            "source": "intraday_scan",
        }

    _DAY_INTRADAY_BEST[ds] = out
    return out


def _load_last_intraday_scan(day: date, code: str, *, settings: Optional[dict[str, Any]] = None) -> Optional[dict[str, Any]]:
    """Last intraday scan MSS for ``code`` on ``day`` (DB → job manifests)."""
    try:
        from agent_reach.daily_run.storage.config import path_under_daily_run_data

        if path_under_daily_run_data(runs_dir()):
            from agent_reach.daily_run.storage.readers import read_intraday_scan_best_for_day

            if settings is None:
                from agent_reach.daily_run.settings import load_settings

                settings = load_settings()
            hit = read_intraday_scan_best_for_day(day, code, settings=settings)
            if hit:
                return hit
    except Exception:
        pass
    norm = _normalize_code(code)
    hit = _intraday_best_scans_for_day(day).get(norm)
    if not hit:
        return None
    return dict(hit)


def prior_close_date_label(report: dict[str, Any]) -> str:
    """Human-readable prior-close date for cards (marks stale snapshots)."""
    date_label = str(report.get("prior_close_date") or "昨收")
    if report.get("prior_close_stale") or report.get("prior_close_source") == "close_baseline_stale":
        return f"{date_label}·过期"
    scan_id = report.get("prior_close_scan_id")
    if scan_id and str(report.get("prior_close_source") or "").startswith("intraday_scan"):
        return f"{date_label}·{scan_id}"
    return date_label


def load_prior_close_reference(
    code: str,
    settings: Optional[dict[str, Any]] = None,
    *,
    as_of: Optional[date] = None,
) -> Optional[dict[str, Any]]:
    """Load yesterday close MSS for a symbol (baseline → manifest → intraday scan → stale)."""
    if settings and not prior_close_enabled(settings):
        return None

    norm = _normalize_code(str(code))
    if not norm or norm == "MARKET":
        return None

    target_day = prev_trading_day(as_of, settings=settings or {})
    target_ds = target_day.isoformat()

    baseline = load_close_baseline(norm)
    if baseline:
        close_date = str(baseline.get("close_date") or "")[:10]
        if close_date == target_ds or not close_date:
            return {
                **baseline,
                "close_date": close_date or target_ds,
                "source": str(baseline.get("_baseline_source") or "close_baseline"),
            }

    manifest = _load_close_from_manifest(target_day, norm)
    if manifest:
        return {**manifest, "source": manifest.get("_baseline_source", "manifest")}

    intraday = _load_last_intraday_scan(target_day, norm, settings=settings or {})
    if intraday:
        return intraday

    if baseline:
        return {
            **baseline,
            "close_date": str(baseline.get("close_date") or target_ds)[:10],
            "source": "close_baseline_stale",
            "prior_close_stale": True,
        }
    return None


def attach_prior_close_reference(
    snapshot: dict[str, Any],
    settings: Optional[dict[str, Any]] = None,
) -> dict[str, Any]:
    """Attach prior close MSS fields to a premarket snapshot."""
    cfg = settings or {}
    if not prior_close_enabled(cfg):
        return snapshot
    if snapshot.get("report_type") not in (None, "premarket"):
        return snapshot

    code = snapshot.get("code")
    if not code or str(code) == "MARKET":
        return snapshot

    prior = load_prior_close_reference(str(code), cfg)
    if not prior or prior.get("mss_final") is None:
        return snapshot

    out = dict(snapshot)
    out["prior_close_mss"] = float(prior["mss_final"])
    out["prior_close_verdict"] = prior.get("verdict")
    out["prior_close_date"] = prior.get("close_date")
    out["prior_close_source"] = prior.get("source")
    out["prior_close_stale"] = bool(prior.get("prior_close_stale"))
    out["prior_close_scan_id"] = prior.get("scan_id")
    if prior.get("mss_breakdown"):
        out["prior_close_breakdown"] = prior["mss_breakdown"]
    return out


def format_prior_close_line(report: dict[str, Any]) -> str:
    """Render '昨收 MSS → 今晨 MSS' line for Feishu cards."""
    prior = report.get("prior_close_mss")
    if prior is None:
        return ""
    current = report.get("mss_final")
    delta = report.get("prior_close_delta")
    date_label = prior_close_date_label(report)
    verdict = report.get("prior_close_verdict")
    parts = [f"**昨收 MSS（{date_label}）：** {prior}"]
    if verdict:
        parts[0] += f"（{verdict}）"
    if current is not None:
        delta_s = f"（{delta:+.1f}）" if delta is not None else ""
        parts.append(f"→ 今晨 **{current}**{delta_s}")
    return " ".join(parts)
