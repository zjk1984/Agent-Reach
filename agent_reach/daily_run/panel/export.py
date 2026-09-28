# -*- coding: utf-8 -*-
"""Static HTML export generator for daily-run mission control panel.

Generates self-contained HTML reports with embedded data for offline viewing,
archiving, or sharing via Feishu / email.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Optional

from agent_reach.daily_run.panel.reader import PanelDataReader
from agent_reach.daily_run.panel.server import get_panel_html
from agent_reach.daily_run.storage.config import daily_run_data_root


def export_panel_html(
    output_path: Optional[Path] = None,
    db_path: Optional[Path] = None,
    data_root: Optional[Path] = None,
) -> Path:
    """Generate and write a standalone HTML report containing the latest state."""
    reader = PanelDataReader(db_path=db_path, data_root=data_root)
    state = reader.get_full_panel_state()

    out_file = output_path
    if out_file is None:
        root = data_root or daily_run_data_root()
        out_file = Path(root).expanduser() / "panel_report.html"
    else:
        out_file = Path(out_file).expanduser()

    out_file.parent.mkdir(parents=True, exist_ok=True)

    html = get_panel_html(state)
    # Mark as static export
    script_flag = "<script>window.__STATIC_EXPORT__ = true;</script>"
    if "</head>" in html:
        html = html.replace("</head>", f"{script_flag}\n</head>", 1)
    else:
        html = script_flag + "\n" + html

    out_file.write_text(html, encoding="utf-8")
    return out_file
