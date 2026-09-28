# -*- coding: utf-8 -*-
"""Starlette-powered live HTTP and SSE API server for daily-run mission control panel.

Provides REST and SSE endpoints for the web dashboard.
Strictly read-only; does not write to the SQLite database.
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
import sys
from pathlib import Path
from typing import Any, AsyncGenerator, Optional

from starlette.applications import Starlette
from starlette.middleware import Middleware
from starlette.middleware.cors import CORSMiddleware
from starlette.requests import Request
from starlette.responses import HTMLResponse, JSONResponse, StreamingResponse
from starlette.routing import Route

from agent_reach.daily_run.panel.reader import PanelDataReader

logger = logging.getLogger("agent_reach.daily_run.panel")


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


class PanelServer:
    """Web server managing panel endpoints and live SSE event streams."""

    def __init__(
        self,
        reader: Optional[PanelDataReader] = None,
        host: str = "127.0.0.1",
        port: int = 8788,
    ) -> None:
        self.reader = reader or PanelDataReader()
        self.host = host
        self.port = port
        self.app = self._create_app()

    def _create_app(self) -> Starlette:
        routes = [
            Route("/", endpoint=self.handle_index, methods=["GET"]),
            Route("/api/status", endpoint=self.handle_status, methods=["GET"]),
            Route("/api/regime", endpoint=self.handle_regime, methods=["GET"]),
            Route("/api/deviations", endpoint=self.handle_deviations, methods=["GET"]),
            Route("/api/events", endpoint=self.handle_events, methods=["GET"]),
            Route("/api/full", endpoint=self.handle_full, methods=["GET"]),
            Route("/api/events/stream", endpoint=self.handle_events_stream, methods=["GET"]),
        ]

        middleware = [
            Middleware(
                CORSMiddleware,
                allow_origins=["*"],
                allow_methods=["*"],
                allow_headers=["*"],
            )
        ]

        return Starlette(debug=False, routes=routes, middleware=middleware)

    async def handle_index(self, request: Request) -> HTMLResponse:
        """Serve the single-page dashboard with pre-rendered initial state."""
        try:
            full_state = await asyncio.to_thread(self.reader.get_full_panel_state)
            html = get_panel_html(full_state)
        except Exception:
            html = get_panel_html(None)
        return HTMLResponse(content=html, media_type="text/html")

    async def handle_status(self, request: Request) -> JSONResponse:
        """Return portfolio and holding status."""
        data = await asyncio.to_thread(self.reader.get_portfolio_status)
        return JSONResponse(data)

    async def handle_regime(self, request: Request) -> JSONResponse:
        """Return TSP market sentiment regime and mainline rankings."""
        data = await asyncio.to_thread(self.reader.get_tsp_regime)
        return JSONResponse(data)

    async def handle_deviations(self, request: Request) -> JSONResponse:
        """Return exchange price deviation radar."""
        data = await asyncio.to_thread(self.reader.get_deviation_radar)
        return JSONResponse(data)

    async def handle_events(self, request: Request) -> JSONResponse:
        """Return recent L0 events."""
        limit = int(request.query_params.get("limit", 40))
        since = request.query_params.get("since", "")
        data = await asyncio.to_thread(self.reader.get_recent_events, limit=limit, since=since)
        return JSONResponse(data)

    async def handle_full(self, request: Request) -> JSONResponse:
        """Return the complete unified panel state."""
        data = await asyncio.to_thread(self.reader.get_full_panel_state)
        return JSONResponse(data)

    async def handle_events_stream(self, request: Request) -> StreamingResponse:
        """Stream real-time server-sent events (SSE) to the browser."""

        async def event_generator() -> AsyncGenerator[str, None]:
            last_event_id = 0
            # Send initial full state immediately on connect
            try:
                initial_state = await asyncio.to_thread(self.reader.get_full_panel_state)
                events = initial_state.get("events", [])
                if events:
                    last_event_id = events[0].get("id", 0)
                yield f"event: state\ndata: {json.dumps(initial_state, ensure_ascii=False)}\n\n"
            except Exception as e:
                yield f"event: error\ndata: {json.dumps({'error': str(e)})}\n\n"

            # SSE heartbeat & update loop
            while True:
                if await request.is_disconnected():
                    break
                await asyncio.sleep(3.0)
                try:
                    # Check for new events
                    recent = await asyncio.to_thread(self.reader.get_recent_events, limit=10)
                    new_events = [ev for ev in recent if ev.get("id", 0) > last_event_id]
                    if new_events:
                        last_event_id = max(ev.get("id", 0) for ev in new_events)
                        yield f"event: new_events\ndata: {json.dumps(new_events, ensure_ascii=False)}\n\n"

                    # Push regular heartbeat with market status
                    heartbeat_data = {
                        "time": asyncio.get_event_loop().time(),
                        "beijing_time": self.reader.get_full_panel_state().get("meta", {}).get("beijing_time", ""),
                    }
                    yield f"event: heartbeat\ndata: {json.dumps(heartbeat_data)}\n\n"
                except Exception:
                    # Keep stream alive on transient errors
                    pass

        return StreamingResponse(
            event_generator(),
            media_type="text/event-stream",
            headers={
                "Cache-Control": "no-cache",
                "Connection": "keep-alive",
                "X-Accel-Buffering": "no",
            },
        )


def serve_panel(
    host: str = "127.0.0.1",
    port: int = 8788,
    open_browser: bool = False,
    db_path: Optional[Path] = None,
) -> None:
    """Start the Uvicorn web server hosting the mission control panel."""
    import uvicorn

    reader = PanelDataReader(db_path=db_path)
    server = PanelServer(reader=reader, host=host, port=port)

    url = f"http://{host}:{port}"
    print(f"🚀 Daily-Run 实时量化态势大屏启动中...")
    print(f"📍 访问地址: {url}")
    print(f"💾 数据源: {reader.db_path} (只读模式)")
    print(f"按 Ctrl+C 停止服务\n")

    if open_browser:
        try:
            import webbrowser
            webbrowser.open(url)
        except Exception:
            pass

    uvicorn.run(server.app, host=host, port=port, log_level="warning")


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
