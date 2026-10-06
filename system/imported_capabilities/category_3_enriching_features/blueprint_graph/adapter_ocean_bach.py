# -*- coding: utf-8 -*-
# SPDX-License-Identifier: MIT
"""
Bach & Ocean Adapter for Dynamic SVG Blueprint & Circuit Graphs (from SentinelFleet & NemoFold).

Generates dependency graphs and architecture circuit diagrams as standalone SVG
without external runtime dependencies (no graphviz, no npm).
Enriches:
- Ocean: Interactive visualization of recipe components, dependencies, and pinned hashes.
- Bach: Visual system circuit of active services, connectors, and agent swarms.
"""

from __future__ import annotations

import html
from dataclasses import dataclass
from typing import Dict, List, Optional, Tuple


@dataclass
class GraphNode:
    id: str
    label: str
    category: str  # service, connector, agent, memory, recipe_package
    status: str    # active, idle, blocked, pinned
    metadata: Dict[str, str]


@dataclass
class GraphEdge:
    source_id: str
    target_id: str
    label: Optional[str] = None
    style: str = "solid"  # solid, dashed, warning


class CircuitSvgGenerator:
    """Generates clean, responsive SVG diagrams for Bach and Ocean."""

    CATEGORY_COLORS = {
        "service": "#2563eb",         # Blue
        "connector": "#059669",       # Green
        "agent": "#7c3aed",           # Purple
        "memory": "#d97706",          # Amber
        "recipe_package": "#0284c7",  # Sky
        "default": "#4b5563",         # Slate
    }

    STATUS_STROKES = {
        "active": "#10b981",   # Green border
        "idle": "#6b7280",     # Gray border
        "blocked": "#ef4444",  # Red border
        "pinned": "#3b82f6",   # Blue border
    }

    @classmethod
    def render_svg(
        cls,
        nodes: List[GraphNode],
        edges: List[GraphEdge],
        title: str = "System Circuit Topology",
        width: int = 1000,
        height: int = 600,
    ) -> str:
        """Renders an interactive SVG string."""
        svg_lines = [
            f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {width} {height}" '
            f'width="100%" height="100%" style="background-color: #0f172a; font-family: sans-serif;">',
            '  <defs>',
            '    <marker id="arrow" viewBox="0 0 10 10" refX="10" refY="5" markerWidth="6" markerHeight="6" orient="auto-start-reverse">',
            '      <path d="M 0 0 L 10 5 L 0 10 z" fill="#94a3b8" />',
            '    </marker>',
            '    <filter id="glow" x="-20%" y="-20%" width="140%" height="140%">',
            '      <feDropShadow dx="0" dy="4" stdDeviation="6" flood-color="#000000" flood-opacity="0.4" />',
            '    </filter>',
            '  </defs>',
            f'  <text x="30" y="40" fill="#f8fafc" font-size="20" font-weight="bold">{html.escape(title)}</text>',
        ]

        # Layout nodes in grid/columns
        node_positions: Dict[str, Tuple[int, int]] = {}
        cols = 3
        col_width = (width - 100) // cols
        row_height = 110

        for idx, node in enumerate(nodes):
            c = idx % cols
            r = idx // cols
            x = 50 + c * col_width + 20
            y = 70 + r * row_height
            node_positions[node.id] = (x, y)

        # Draw Edges
        for edge in edges:
            if edge.source_id in node_positions and edge.target_id in node_positions:
                x1, y1 = node_positions[edge.source_id]
                x2, y2 = node_positions[edge.target_id]
                # Center of node boxes (box is 220x60)
                cx1, cy1 = x1 + 110, y1 + 30
                cx2, cy2 = x2 + 110, y2 + 30
                stroke_dash = 'stroke-dasharray="5,5"' if edge.style == "dashed" else ""
                svg_lines.append(
                    f'  <line x1="{cx1}" y1="{cy1}" x2="{cx2}" y2="{cy2}" stroke="#64748b" stroke-width="2" '
                    f'{stroke_dash} marker-end="url(#arrow)" />'
                )
                if edge.label:
                    mx, my = (cx1 + cx2) // 2, (cy1 + cy2) // 2 - 5
                    svg_lines.append(
                        f'  <text x="{mx}" y="{my}" fill="#94a3b8" font-size="11" text-anchor="middle">{html.escape(edge.label)}</text>'
                    )

        # Draw Nodes
        for node in nodes:
            x, y = node_positions[node.id]
            fill_color = cls.CATEGORY_COLORS.get(node.category, cls.CATEGORY_COLORS["default"])
            stroke_color = cls.STATUS_STROKES.get(node.status, "#475569")

            svg_lines.append(f'  <g id="node_{html.escape(node.id)}" filter="url(#glow)">')
            svg_lines.append(
                f'    <rect x="{x}" y="{y}" width="220" height="60" rx="8" '
                f'fill="{fill_color}" fill-opacity="0.25" stroke="{stroke_color}" stroke-width="2" />'
            )
            svg_lines.append(
                f'    <text x="{x + 12}" y="{y + 24}" fill="#f1f5f9" font-size="14" font-weight="bold">{html.escape(node.label)}</text>'
            )
            subtext = f"{node.category.upper()} · {node.status.upper()}"
            svg_lines.append(
                f'    <text x="{x + 12}" y="{y + 44}" fill="#94a3b8" font-size="11">{html.escape(subtext)}</text>'
            )
            svg_lines.append('  </g>')

        svg_lines.append('</svg>')
        return "\n".join(svg_lines)
