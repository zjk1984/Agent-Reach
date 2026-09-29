# -*- coding: utf-8 -*-
"""Read-only data aggregator for daily-run mission control panel.

Strictly read-only access to SQLite database and daily-run JSON artifacts.
Adheres to SQLite prod guard: never executes writes or locks against the production DB.
"""

from __future__ import annotations

import json
import os
import sqlite3
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Generator, Optional

from agent_reach.daily_run.settings import effective_settings, load_settings
from agent_reach.daily_run.storage.config import daily_run_data_root, sqlite_db_path
from agent_reach.daily_run.tsp.deviation_monitor import compute_exchange_deviation_risk
from agent_reach.daily_run.tsp.intraday_sentinel import (
    check_intraday_retreat_risk,
    get_live_market_breadth_and_phase,
)


class PanelDataReader:
    """Read-only data provider extracting live telemetry from daily-run storage."""

    def __init__(
        self,
        db_path: Optional[Path] = None,
        data_root: Optional[Path] = None,
        settings: Optional[dict[str, Any]] = None,
    ) -> None:
        self.settings = effective_settings(settings or load_settings())
        self.data_root = Path(data_root or daily_run_data_root()).expanduser()
        self.db_path = Path(db_path or sqlite_db_path(self.settings)).expanduser()

    @contextmanager
    def _ro_conn(self) -> Generator[Optional[sqlite3.Connection], None, None]:
        """Open SQLite connection strictly in URI read-only mode."""
        if not self.db_path.exists():
            yield None
            return

        uri = f"file:{self.db_path.resolve()}?mode=ro"
        try:
            conn = sqlite3.connect(uri, uri=True, timeout=5)
            conn.row_factory = sqlite3.Row
            try:
                yield conn
            finally:
                conn.close()
        except sqlite3.OperationalError:
            # Fallback for systems where URI mode may hit permission checks
            try:
                conn = sqlite3.connect(str(self.db_path.resolve()), timeout=5)
                conn.row_factory = sqlite3.Row
                try:
                    yield conn
                finally:
                    conn.close()
            except Exception:
                yield None

    def get_portfolio_status(self) -> dict[str, Any]:
        """Extract latest portfolio snapshot and holdings."""
        cash = 0.0
        total = 0.0
        as_of = ""
        holdings: list[dict[str, Any]] = []

        # 1. Try SQLite first
        with self._ro_conn() as conn:
            if conn:
                try:
                    snap = conn.execute(
                        "SELECT at, cash, total, payload_json FROM portfolio_snapshots ORDER BY id DESC LIMIT 1"
                    ).fetchone()
                    if snap:
                        cash = float(snap["cash"] or 0.0)
                        total = float(snap["total"] or 0.0)
                        as_of = str(snap["at"] or "")

                    pos_rows = conn.execute(
                        "SELECT code, name, shares, cost, payload_json, updated_at FROM positions WHERE shares > 0"
                    ).fetchall()
                    for r in pos_rows:
                        payload = {}
                        if r["payload_json"]:
                            try:
                                payload = json.loads(r["payload_json"])
                            except Exception:
                                payload = {}
                        price = float(payload.get("price") or r["cost"] or 0.0)
                        shares = int(r["shares"] or 0)
                        cost = float(r["cost"] or 0.0)
                        market_val = round(shares * price, 2)
                        cost_val = round(shares * cost, 2)
                        pnl = round(market_val - cost_val, 2)
                        pnl_pct = round((pnl / cost_val * 100.0) if cost_val > 0 else 0.0, 2)

                        holdings.append(
                            {
                                "code": str(r["code"]),
                                "name": str(r["name"] or payload.get("name") or r["code"]),
                                "shares": shares,
                                "cost": cost,
                                "price": price,
                                "market_value": market_val,
                                "unrealized_pnl": pnl,
                                "unrealized_pnl_pct": pnl_pct,
                                "change_pct": float(payload.get("change_pct") or 0.0),
                                "ma20": float(payload.get("ma20") or 0.0),
                                "days_held": int(payload.get("days_held") or 0),
                            }
                        )
                except Exception:
                    pass

        # 2. Fall back to portfolio.json if SQLite had no positions or snapshot
        if (total == 0.0 or not holdings) and (self.data_root / "portfolio.json").exists():
            try:
                with open(self.data_root / "portfolio.json", "r", encoding="utf-8") as fp:
                    p = json.load(fp)
                    cash = float(p.get("cash") or cash)
                    total = float(p.get("total") or total)
                    as_of = as_of or str(p.get("trade_session_date") or "")
                    if not holdings:
                        for h in p.get("holdings") or []:
                            if not isinstance(h, dict):
                                continue
                            shares = int(h.get("shares") or 0)
                            if shares <= 0:
                                continue
                            price = float(h.get("price") or h.get("cost") or 0.0)
                            cost = float(h.get("cost") or 0.0)
                            market_val = round(shares * price, 2)
                            cost_val = round(shares * cost, 2)
                            pnl = round(market_val - cost_val, 2)
                            pnl_pct = round((pnl / cost_val * 100.0) if cost_val > 0 else 0.0, 2)
                            holdings.append(
                                {
                                    "code": str(h.get("code") or ""),
                                    "name": str(h.get("name") or h.get("code") or ""),
                                    "shares": shares,
                                    "cost": cost,
                                    "price": price,
                                    "market_value": market_val,
                                    "unrealized_pnl": pnl,
                                    "unrealized_pnl_pct": pnl_pct,
                                    "change_pct": float(h.get("change_pct") or 0.0),
                                    "ma20": float(h.get("ma20") or 0.0),
                                    "days_held": int(h.get("days_held") or 0),
                                }
                            )
            except Exception:
                pass

        market_value = sum(h["market_value"] for h in holdings)
        if total <= 0.0:
            total = round(cash + market_value, 2)
        cash_ratio = round((cash / total * 100.0) if total > 0 else 0.0, 1)

        total_unrealized_pnl = round(sum(h["unrealized_pnl"] for h in holdings), 2)
        total_cost = sum(h["shares"] * h["cost"] for h in holdings)
        total_pnl_pct = round((total_unrealized_pnl / total_cost * 100.0) if total_cost > 0 else 0.0, 2)

        return {
            "total_equity": total,
            "cash": cash,
            "market_value": round(market_value, 2),
            "cash_ratio": cash_ratio,
            "unrealized_pnl": total_unrealized_pnl,
            "unrealized_pnl_pct": total_pnl_pct,
            "holdings_count": len(holdings),
            "holdings": holdings,
            "as_of": as_of or datetime.now(timezone.utc).isoformat(),
        }

    def get_tsp_regime(self) -> dict[str, Any]:
        """Query live market breadth, 6-phase sentiment regime and mainline rankings."""
        from agent_reach.daily_run.tsp.intraday_sentinel import normalize_breadth_for_panel

        breadth = normalize_breadth_for_panel(get_live_market_breadth_and_phase(self.settings))
        phase = breadth.get("phase", "unknown")
        broken_rate = float(breadth.get("broken_board_rate") or 0.0)
        down_limit = int(breadth.get("down_limit_count") or 0)

        # Check retreat risk
        retreat_triggered, retreat_reason = check_intraday_retreat_risk(breadth)

        phase_badges = {
            "freezing": {"label": "冰点期 🧊", "color": "#3b82f6", "step": 1},
            "launching": {"label": "启动期 🚀", "color": "#10b981", "step": 2},
            "main_up": {"label": "主升期 🔥", "color": "#ef4444", "step": 3},
            "climax": {"label": "高潮期 ⚡", "color": "#f59e0b", "step": 4},
            "retreat": {"label": "退潮期 🛑", "color": "#dc2626", "step": 5},
            "repair": {"label": "修复期 🩹", "color": "#8b5cf6", "step": 6},
        }

        badge_info = phase_badges.get(
            phase, {"label": f"{phase} ❓", "color": "#6b7280", "step": 0}
        )

        top_mainlines = []
        for m in (breadth.get("top_mainlines") or [])[:5]:
            top_mainlines.append(
                {
                    "sector": m.get("sector", ""),
                    "score": round(float(m.get("score") or 0.0), 1),
                    "leader_stock": m.get("leader_stock", ""),
                    "limit_up_count": int(m.get("limit_up_count") or 0),
                }
            )

        from agent_reach.daily_run.eastmoney_breadth_collector import format_breadth_source_label

        return {
            "phase": phase,
            "phase_label": badge_info["label"],
            "phase_color": badge_info["color"],
            "phase_step": badge_info["step"],
            "description": breadth.get("description", ""),
            "up_count": int(breadth.get("up_count") or 0),
            "down_count": int(breadth.get("down_count") or 0),
            "limit_up_count": int(breadth.get("limit_up_count") or 0),
            "down_limit_count": down_limit,
            "broken_board_rate": broken_rate,
            "max_limit_up_streak": int(breadth.get("max_limit_up_streak") or 0),
            "retreat_triggered": retreat_triggered,
            "retreat_reason": retreat_reason,
            "promotion_ladder": breadth.get("promotion_ladder") or {},
            "top_mainlines": top_mainlines,
            "source": str(breadth.get("source") or ""),
            "ladder_degraded": bool(breadth.get("ladder_degraded")),
            "limit_degraded": bool(breadth.get("limit_degraded")),
            "data_source_label": format_breadth_source_label(breadth),
            "as_of": breadth.get("as_of", datetime.now(timezone.utc).isoformat()),
        }

    def get_deviation_radar(self) -> list[dict[str, Any]]:
        """Calculate exchange abnormal move price deviation radar for portfolio + watchlist."""
        symbols_to_check: list[dict[str, Any]] = []

        # 1. Gather holdings
        p_status = self.get_portfolio_status()
        for h in p_status.get("holdings", []):
            symbols_to_check.append(
                {
                    "code": h["code"],
                    "name": h["name"],
                    "is_holding": True,
                    "price": h["price"],
                }
            )

        # 2. Gather watchlist symbols from portfolio.json if available
        if (self.data_root / "portfolio.json").exists():
            try:
                with open(self.data_root / "portfolio.json", "r", encoding="utf-8") as fp:
                    p = json.load(fp)
                    for item in p.get("watchlist") or []:
                        if isinstance(item, dict):
                            code = str(item.get("code") or "")
                            name = str(item.get("name") or code)
                        else:
                            code = str(item)
                            name = code
                        if code and not any(s["code"] == code for s in symbols_to_check):
                            symbols_to_check.append(
                                {
                                    "code": code,
                                    "name": name,
                                    "is_holding": False,
                                    "price": 0.0,
                                }
                            )
            except Exception:
                pass

        results: list[dict[str, Any]] = []
        for s in symbols_to_check[:15]:
            dev_risk = compute_exchange_deviation_risk(s)
            dist_3d = float(dev_risk.get("distance_to_limit_pct") or 20.0)
            threshold_3d = float(dev_risk.get("threshold_3d_pct") or 20.0)
            cum_3d = float(dev_risk.get("cumulative_3d_pct") or 0.0)
            is_warn = bool(dev_risk.get("warning_triggered", False))

            risk_level = "safe"
            if is_warn:
                risk_level = "critical"
            elif dist_3d < 5.0:
                risk_level = "warning"

            results.append(
                {
                    "code": s["code"],
                    "name": s["name"],
                    "is_holding": s["is_holding"],
                    "price": s["price"],
                    "cumulative_3d_pct": round(cum_3d, 2),
                    "threshold_3d_pct": round(threshold_3d, 1),
                    "distance_to_limit_pct": round(dist_3d, 2),
                    "warning_triggered": is_warn,
                    "risk_level": risk_level,
                    "warning_message": dev_risk.get("warning_message", ""),
                }
            )

        # Sort: critical first, then warning, then ascending distance to limit
        level_order = {"critical": 0, "warning": 1, "safe": 2}
        results.sort(key=lambda x: (level_order.get(x["risk_level"], 9), x["distance_to_limit_pct"]))
        return results

    def get_recent_events(self, limit: int = 40, since: str = "") -> list[dict[str, Any]]:
        """Query recent decision and scan events from L0 event log."""
        events: list[dict[str, Any]] = []
        with self._ro_conn() as conn:
            if not conn:
                return events

            try:
                where_clauses = ["kind IN ('trade', 'intraday_scan', 'session_overlay', 'portfolio')"]
                params: list[Any] = []
                if since:
                    where_clauses.append("at >= ?")
                    params.append(since)

                sql = f"""
                    SELECT id, kind, at, payload_json
                    FROM l0_events
                    WHERE {' AND '.join(where_clauses)}
                    ORDER BY id DESC
                    LIMIT ?
                """
                params.append(max(1, limit))
                rows = conn.execute(sql, params).fetchall()

                for r in rows:
                    p = {}
                    if r["payload_json"]:
                        try:
                            p = json.loads(r["payload_json"])
                        except Exception:
                            p = {}

                    event_type = r["kind"]
                    title = ""
                    summary = ""
                    badge = ""
                    details = {}

                    if event_type == "trade":
                        action_kind = p.get("decision_action", "")
                        acts = p.get("actions", [])
                        title = f"交易执行: {action_kind.upper()}"
                        trade_lines = []
                        for act in acts:
                            side = act.get("side", "")
                            c = act.get("code", "")
                            n = act.get("name", "")
                            pr = act.get("price", 0.0)
                            sh = act.get("shares", 0)
                            pnl = act.get("realized_pnl")
                            trade_lines.append(f"{side} {n}({c}) {sh}股 @ ¥{pr}")
                            if pnl is not None:
                                trade_lines.append(f"盈亏: {pnl:+0.2f}元")
                        summary = " | ".join(trade_lines)
                        badge = "trade"
                        details = p

                    elif event_type == "intraday_scan":
                        scan_id = p.get("scan_id", "")
                        code = p.get("code", "")
                        name = p.get("name", "")
                        verdict = p.get("verdict", "")
                        mss = p.get("mss_final", 0.0)
                        title = f"盘中扫描 [{scan_id}]: {name}({code})"
                        summary = f"结论: {verdict} | MSS: {mss} | 置信度: {p.get('confidence', '')}"
                        badge = "scan"
                        details = p

                    elif event_type == "session_overlay":
                        session = p.get("session", "")
                        regime = p.get("merged_regime", "")
                        title = f"时段修正 [{session}]"
                        summary = f"市场定性: {regime}"
                        badge = "overlay"
                        details = p

                    elif event_type == "portfolio":
                        cash = p.get("cash", 0.0)
                        total = p.get("total", 0.0)
                        title = "资产净值更新"
                        summary = f"总资产: ¥{total:,.2f} | 现金: ¥{cash:,.2f}"
                        badge = "portfolio"
                        details = p

                    events.append(
                        {
                            "id": r["id"],
                            "kind": event_type,
                            "badge": badge,
                            "at": r["at"],
                            "title": title,
                            "summary": summary,
                            "details": details,
                        }
                    )
            except Exception:
                pass

        return events

    def get_intraday_scans_today(self) -> dict[str, Any]:
        """Aggregate intraday scans by scan cycle (S1 to S10)."""
        scans_by_cycle: dict[str, list[dict[str, Any]]] = {}
        for i in range(1, 11):
            scans_by_cycle[f"S{i}"] = []

        with self._ro_conn() as conn:
            if conn:
                try:
                    # Query today's scans
                    today_prefix = datetime.now().strftime("%Y-%m-%d")
                    rows = conn.execute(
                        """
                        SELECT at, payload_json FROM l0_events
                        WHERE kind = 'intraday_scan' AND at LIKE ?
                        ORDER BY id ASC
                        """,
                        (f"{today_prefix}%",),
                    ).fetchall()

                    for r in rows:
                        p = json.loads(r["payload_json"])
                        sid = p.get("scan_id", "")
                        if sid in scans_by_cycle:
                            scans_by_cycle[sid].append(
                                {
                                    "at": r["at"],
                                    "code": p.get("code", ""),
                                    "name": p.get("name", ""),
                                    "price": p.get("price", 0.0),
                                    "mss_final": p.get("mss_final", 0.0),
                                    "verdict": p.get("verdict", ""),
                                    "confidence": p.get("confidence", ""),
                                    "audit_passed": p.get("audit_passed", True),
                                    "broken_board_rate": p.get("broken_board_rate"),
                                    "limit_up_count": p.get("limit_up_count"),
                                }
                            )
                except Exception:
                    pass

        # Build sparkline trajectory for S1..S10
        sparkline_points: list[dict[str, Any]] = []
        for i in range(1, 11):
            sid = f"S{i}"
            items = scans_by_cycle.get(sid) or []
            if items:
                # Average mss_final if multiple symbols scanned in that cycle
                mss_vals = [float(it.get("mss_final") or 0.0) for it in items if it.get("mss_final") is not None]
                avg_mss = round(sum(mss_vals) / len(mss_vals), 1) if mss_vals else 0.0
                time_str = items[0]["at"].split("T")[1].split(".")[0] if "T" in items[0]["at"] else items[0]["at"]
                sparkline_points.append({
                    "cycle": sid,
                    "at": time_str,
                    "mss": avg_mss,
                    "verdict": items[0].get("verdict") or "观察",
                    "symbols_count": len(items),
                })

        completed_cycles = [sid for sid, lst in scans_by_cycle.items() if len(lst) > 0]
        return {
            "total_cycles": 10,
            "completed_cycles_count": len(completed_cycles),
            "completed_cycles": completed_cycles,
            "scans": scans_by_cycle,
            "sparkline": sparkline_points,
        }

    def get_full_panel_state(self, current_report_file: Optional[Path | str] = None) -> dict[str, Any]:
        """Return the complete state package for dashboard rendering."""
        portfolio = self.get_portfolio_status()
        regime = self.get_tsp_regime()
        deviations = self.get_deviation_radar()
        events = self.get_recent_events(limit=30)
        intraday = self.get_intraday_scans_today()

        now = datetime.now(timezone.utc)
        beijing_now = datetime.now()

        # Determine market session
        hour = beijing_now.hour
        minute = beijing_now.minute
        time_int = hour * 100 + minute

        market_status = "休市中"
        if beijing_now.weekday() < 5:
            if 915 <= time_int < 930:
                market_status = "盘前竞价 🔔"
            elif 930 <= time_int < 1130:
                market_status = "早盘交易中 🟢"
            elif 1130 <= time_int < 1300:
                market_status = "午盘休市 ⏸️"
            elif 1300 <= time_int < 1500:
                market_status = "午后交易中 🟢"
            elif 1500 <= time_int < 1530:
                market_status = "收盘清算中 ⏳"
            else:
                market_status = "已收盘 💤"
        else:
            market_status = "周末休市 🏖️"

        # Discover recent report snapshots for historical report selector
        history_reports: list[dict[str, Any]] = []
        try:
            from agent_reach.daily_run.panel.config import list_recent_report_snapshots

            history_reports = list_recent_report_snapshots(
                repo_root=self.data_root.parent if self.data_root.name == "daily_run" else None,
                current_file=current_report_file,
            )
        except Exception:
            pass

        # D1~D6 data router provenance probe
        data_provenance: dict[str, Any] = {}
        try:
            from agent_reach.daily_run.data_router import get_market_data_router

            router = get_market_data_router()
            data_provenance = router.get_provenance_status()
        except Exception:
            pass

        return {
            "meta": {
                "system_name": "Agent Reach Daily-Run Mission Control",
                "version": "1.5.0",
                "updated_at": now.isoformat(),
                "beijing_time": beijing_now.strftime("%Y-%m-%d %H:%M:%S"),
                "market_status": market_status,
                "db_connected": self.db_path.exists(),
                "history_reports": history_reports,
                "data_provenance": data_provenance,
            },
            "portfolio": portfolio,
            "regime": regime,
            "deviations": deviations,
            "intraday": intraday,
            "events": events,
        }
