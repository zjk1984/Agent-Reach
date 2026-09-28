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
from agent_reach.daily_run.storage.config import daily_run_data_root

_FALLBACK_INDEX_HTML = """<!DOCTYPE html>
<html lang="zh-CN">
<head>
  <meta charset="UTF-8">
  <meta name="viewport" content="width=device-width, initial-scale=1.0">
  <title>Agent Reach Daily-Run 实时量化态势大屏</title>
  <style>
    body { background-color: #0b0f19; color: #f3f4f6; font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, sans-serif; margin: 0; padding: 2rem; }
    h1 { color: #60a5fa; }
  </style>
</head>
<body>
  <h1>Agent Reach Daily-Run 态势大屏</h1>
  <p>正在加载仪表盘组件...</p>
</body>
</html>
"""


def get_panel_html(initial_data: Optional[dict[str, Any]] = None) -> str:
    """Load the dashboard HTML, optionally injecting initial state for zero-latency load."""
    html_path = Path(__file__).parent / "static" / "index.html"
    if html_path.exists():
        content = html_path.read_text(encoding="utf-8")
    else:
        content = _FALLBACK_INDEX_HTML

    if initial_data:
        json_str = json.dumps(initial_data, ensure_ascii=False)
        # Safely inject into window.__INITIAL_DATA__
        script_inject = f"<script>window.__INITIAL_PANEL_DATA__ = {json_str};</script>"
        if "</head>" in content:
            content = content.replace("</head>", f"{script_inject}\n</head>", 1)
        else:
            content = script_inject + "\n" + content

    return content


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
