# -*- coding: utf-8
"""Feishu interactive card element builder (adapted from Vibe-Trading feishu channel).

Renders markdown into native Feishu card elements (markdown blocks, headings, tables).
Splits into multiple element groups when a card would exceed Feishu's one-table limit.
"""

from __future__ import annotations

import re
from typing import Any

_TABLE_RE = re.compile(
    r"((?:^[ \t]*\|.+\|[ \t]*\n)(?:^[ \t]*\|[-:\s|]+\|[ \t]*\n)(?:^[ \t]*\|.+\|[ \t]*\n?)+)",
    re.MULTILINE,
)
_HEADING_RE = re.compile(r"^(#{1,6})\s+(.+)$", re.MULTILINE)
_CODE_BLOCK_RE = re.compile(r"(```[\s\S]*?```)", re.MULTILINE)

_MD_BOLD_RE = re.compile(r"\*\*(.+?)\*\*")
_MD_BOLD_UNDERSCORE_RE = re.compile(r"__(.+?)__")
_MD_ITALIC_RE = re.compile(r"(?<!\*)\*(?!\*)(.+?)(?<!\*)\*(?!\*)")
_MD_STRIKE_RE = re.compile(r"~~(.+?)~~")


def _strip_md_formatting(text: str) -> str:
    text = _MD_BOLD_RE.sub(r"\1", text)
    text = _MD_BOLD_UNDERSCORE_RE.sub(r"\1", text)
    text = _MD_ITALIC_RE.sub(r"\1", text)
    text = _MD_STRIKE_RE.sub(r"\1", text)
    return text


def _parse_md_table(table_text: str) -> dict[str, Any] | None:
    lines = [line.strip() for line in table_text.strip().split("\n") if line.strip()]
    if len(lines) < 3:
        return None

    def split_row(line: str) -> list[str]:
        return [cell.strip() for cell in line.strip("|").split("|")]

    headers = [_strip_md_formatting(h) for h in split_row(lines[0])]
    rows = [[_strip_md_formatting(c) for c in split_row(line)] for line in lines[2:]]
    columns = [
        {"tag": "column", "name": f"c{i}", "display_name": h, "width": "auto"}
        for i, h in enumerate(headers)
    ]
    return {
        "tag": "table",
        "page_size": len(rows) + 1,
        "columns": columns,
        "rows": [{f"c{i}": row[i] if i < len(row) else "" for i in range(len(headers))} for row in rows],
    }


def _split_headings(content: str) -> list[dict[str, Any]]:
    protected = content
    code_blocks: list[str] = []
    for match in _CODE_BLOCK_RE.finditer(content):
        code_blocks.append(match.group(1))
        protected = protected.replace(match.group(1), f"\x00CODE{len(code_blocks) - 1}\x00", 1)

    elements: list[dict[str, Any]] = []
    last_end = 0
    for match in _HEADING_RE.finditer(protected):
        before = protected[last_end : match.start()].strip()
        if before:
            elements.append({"tag": "markdown", "content": before})
        text = _strip_md_formatting(match.group(2).strip())
        elements.append(
            {
                "tag": "div",
                "text": {"tag": "lark_md", "content": f"**{text}**" if text else ""},
            }
        )
        last_end = match.end()
    remaining = protected[last_end:].strip()
    if remaining:
        elements.append({"tag": "markdown", "content": remaining})

    for i, block in enumerate(code_blocks):
        for el in elements:
            if el.get("tag") == "markdown":
                el["content"] = el["content"].replace(f"\x00CODE{i}\x00", block)

    return elements or [{"tag": "markdown", "content": content}]


def build_card_elements(markdown: str) -> list[dict[str, Any]]:
    """Split markdown into Feishu card elements (markdown / heading div / native table)."""
    content = markdown.strip()
    if not content:
        return [{"tag": "markdown", "content": ""}]

    elements: list[dict[str, Any]] = []
    last_end = 0
    for match in _TABLE_RE.finditer(content):
        before = content[last_end : match.start()]
        if before.strip():
            elements.extend(_split_headings(before))
        table_el = _parse_md_table(match.group(1))
        elements.append(table_el or {"tag": "markdown", "content": match.group(1)})
        last_end = match.end()
    remaining = content[last_end:]
    if remaining.strip():
        elements.extend(_split_headings(remaining))
    return elements or [{"tag": "markdown", "content": content}]


def split_elements_by_table_limit(
    elements: list[dict[str, Any]],
    *,
    max_tables: int = 1,
) -> list[list[dict[str, Any]]]:
    """Group elements so each group has at most *max_tables* table elements."""
    if not elements:
        return [[]]
    groups: list[list[dict[str, Any]]] = []
    current: list[dict[str, Any]] = []
    table_count = 0
    for el in elements:
        if el.get("tag") == "table":
            if table_count >= max_tables:
                if current:
                    groups.append(current)
                current = []
                table_count = 0
            current.append(el)
            table_count += 1
        else:
            current.append(el)
    if current:
        groups.append(current)
    return groups or [[]]


def build_card_payloads(
    title: str,
    markdown: str,
    *,
    template: str = "blue",
    split_tables: bool = True,
) -> list[dict[str, Any]]:
    """Build one or more Feishu interactive card payloads from markdown."""
    elements = build_card_elements(markdown)
    groups = split_elements_by_table_limit(elements) if split_tables else [elements]
    if not groups:
        groups = [elements]

    payloads: list[dict[str, Any]] = []
    for group in groups:
        if not group:
            continue
        payloads.append(
            {
                "config": {"wide_screen_mode": True},
                "header": {
                    "title": {"tag": "plain_text", "content": title},
                    "template": template,
                },
                "elements": group,
            }
        )
    if not payloads:
        payloads.append(
            {
                "config": {"wide_screen_mode": True},
                "header": {
                    "title": {"tag": "plain_text", "content": title},
                    "template": template,
                },
                "elements": [{"tag": "markdown", "content": markdown}],
            }
        )
    return payloads
