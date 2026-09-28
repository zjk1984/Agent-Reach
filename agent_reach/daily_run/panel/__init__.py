# -*- coding: utf-8 -*-
"""Mission control live dashboard and API panel for daily-run.

Inspired by zjk1984/tick-stock-panel:
- Live 6-phase market sentiment regime & breadth meter
- Limit-up ladder and top 5 mainline rankings
- Exchange abnormal move price deviation radar
- Intraday 10-cycle execution telemetry & trade event stream
- Zero-maintenance, read-only sidecar architecture
"""

from __future__ import annotations

from agent_reach.daily_run.panel.reader import PanelDataReader
from agent_reach.daily_run.panel.server import PanelServer, serve_panel
from agent_reach.daily_run.panel.export import export_panel_html

__all__ = [
    "PanelDataReader",
    "PanelServer",
    "serve_panel",
    "export_panel_html",
]
