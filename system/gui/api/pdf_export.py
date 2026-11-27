# SPDX-License-Identifier: MIT
"""Pure-stdlib PDF 1.4 export generator for OCEAN calendar & agenda views.

Generates valid `%PDF-1.4` documents with `/Helvetica` and `/Helvetica-Bold`
Type1 fonts using `/Encoding /WinAnsiEncoding` so German umlauts (`äöüßÄÖÜ`)
and punctuation (`€`, `–`, `—`, `•`) render reliably without external libraries.
"""
from __future__ import annotations

import calendar as pycalendar
from collections.abc import Iterable
from datetime import date
from typing import Any

_WEEKDAYS_SHORT_DE = ("Mo", "Di", "Mi", "Do", "Fr", "Sa", "So")
_MONTHS_DE = (
    "",
    "Januar",
    "Februar",
    "März",
    "April",
    "Mai",
    "Juni",
    "Juli",
    "August",
    "September",
    "Oktober",
    "November",
    "Dezember",
)

_WINANSI_EXTRA: dict[str, int] = {
    "€": 0x80,
    "‚": 0x82,
    "„": 0x84,
    "…": 0x85,
    "‘": 0x91,
    "’": 0x92,
    "“": 0x93,
    "”": 0x94,
    "•": 0x95,
    "–": 0x96,
    "—": 0x97,
    "™": 0x99,
}

_HORIZON_COLORS: dict[str, str] = {
    "short": "#f43f5e",
    "mid": "#38bdf8",
    "long": "#6366f1",
}


def pdf_encode_str(text: str) -> str:
    """Encode Unicode text deterministically as a WinAnsi PDF literal string."""
    buf: list[str] = []
    for ch in text:
        code = ord(ch)
        if ch == "\\":
            buf.append("\\\\")
        elif ch == "(":
            buf.append("\\(")
        elif ch == ")":
            buf.append("\\)")
        elif ch in ("\r", "\n", "\t"):
            buf.append(" ")
        elif 32 <= code <= 126:
            buf.append(ch)
        elif ch in _WINANSI_EXTRA:
            buf.append(f"\\{_WINANSI_EXTRA[ch]:03o}")
        elif 160 <= code <= 255:
            buf.append(f"\\{code:03o}")
        else:
            buf.append("?")
    return "(" + "".join(buf) + ")"


def _hex_to_rgb01(hex_color: str) -> tuple[float, float, float]:
    clean = (hex_color or "#2563eb").lstrip("#")
    if len(clean) == 3:
        clean = "".join(c * 2 for c in clean)
    if len(clean) != 6:
        return (0.15, 0.39, 0.92)
    try:
        r = int(clean[0:2], 16) / 255.0
        g = int(clean[2:4], 16) / 255.0
        b = int(clean[4:6], 16) / 255.0
        return (round(r, 3), round(g, 3), round(b, 3))
    except ValueError:
        return (0.15, 0.39, 0.92)


def assemble_pdf_document(pages_ops: list[str], page_width: float, page_height: float) -> bytes:
    """Build a valid `%PDF-1.4` document with byte-accurate `xref` offsets."""
    if not pages_ops:
        pages_ops = [""]
    num_pages = len(pages_ops)

    objects: dict[int, bytes] = {
        3: b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica /Encoding /WinAnsiEncoding >>",
        4: b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica-Bold /Encoding /WinAnsiEncoding >>",
    }

    kids_refs: list[str] = []
    next_id = 5
    for content_str in pages_ops:
        page_id = next_id
        stream_id = next_id + 1
        next_id += 2
        kids_refs.append(f"{page_id} 0 R")
        stream_bytes = content_str.encode("latin-1", errors="replace")
        objects[stream_id] = (
            f"<< /Length {len(stream_bytes)} >>\nstream\n".encode("ascii")
            + stream_bytes
            + b"\nendstream"
        )
        objects[page_id] = (
            f"<< /Type /Page /Parent 2 0 R "
            f"/MediaBox [0 0 {page_width:.2f} {page_height:.2f}] "
            f"/Resources << /Font << /F1 3 0 R /F2 4 0 R >> >> "
            f"/Contents {stream_id} 0 R >>"
        ).encode("ascii")

    objects[2] = f"<< /Type /Pages /Kids [{' '.join(kids_refs)}] /Count {num_pages} >>".encode("ascii")
    objects[1] = b"<< /Type /Catalog /Pages 2 0 R >>"

    total_objs = next_id - 1
    chunks: list[bytes] = [b"%PDF-1.4\n%\xe2\xe3\xcf\xd3\n"]
    offsets: dict[int, int] = {}
    cursor = len(chunks[0])

    for obj_id in range(1, total_objs + 1):
        offsets[obj_id] = cursor
        block = f"{obj_id} 0 obj\n".encode("ascii") + objects[obj_id] + b"\nendobj\n"
        chunks.append(block)
        cursor += len(block)

    xref_offset = cursor
    xref_lines = [f"xref\n0 {total_objs + 1}\n", "0000000000 65535 f \n"]
    for obj_id in range(1, total_objs + 1):
        xref_lines.append(f"{offsets[obj_id]:010d} 00000 n \n")
    trailer = (
        "".join(xref_lines)
        + f"trailer\n<< /Size {total_objs + 1} /Root 1 0 R >>\n"
        + f"startxref\n{xref_offset}\n%%EOF\n"
    ).encode("ascii")
    chunks.append(trailer)
    return b"".join(chunks)


def _add_page_footers(pages: list[str], pw: float, margin: float) -> list[str]:
    total = len(pages)
    out: list[str] = []
    for idx, ops in enumerate(pages, start=1):
        footer = (
            f"\n0.45 0.5 0.58 rg BT /F1 7.5 Tf {pw - margin - 65:.1f} {margin - 16:.1f} Td "
            f"{pdf_encode_str(f'Seite {idx} / {total}')} Tj ET"
        )
        out.append(ops + footer)
    return out


def _draw_header_banner(
    pw: float,
    ph: float,
    margin: float,
    title: str,
    subtitle: str,
    legend_items: Iterable[tuple[str, str]],
) -> list[str]:
    ops = [
        "0.06 0.09 0.16 rg",
        f"{margin:.1f} {ph - margin - 28:.1f} {pw - 2 * margin:.1f} 28 re f",
        "1 1 1 rg",
        f"BT /F2 12.5 Tf {margin + 10:.1f} {ph - margin - 19:.1f} Td {pdf_encode_str(title[:62])} Tj ET",
        f"BT /F1 8.5 Tf {pw - margin - 205:.1f} {ph - margin - 18:.1f} Td {pdf_encode_str(subtitle[:42])} Tj ET",
    ]
    lx = margin
    ly = ph - margin - 44.0
    for hex_color, label in list(legend_items)[:8]:
        r, g, b = _hex_to_rgb01(hex_color)
        ops.append(f"{r} {g} {b} rg {lx:.1f} {ly:.1f} 8 8 re f")
        ops.append(
            f"0.2 0.25 0.33 rg BT /F1 7.5 Tf {lx + 11:.1f} {ly + 1:.1f} Td {pdf_encode_str(label)} Tj ET"
        )
        lx += max(68.0, len(label) * 4.4 + 18.0)
        if lx > pw - margin - 70.0:
            break
    return ops


def _parse_event_date_time(raw_dt: Any) -> tuple[str, str]:
    s = str(raw_dt or "").strip().replace("T", " ")
    date_part = s[:10] if len(s) >= 10 else ""
    time_part = s[11:16] if len(s) >= 16 and s[10] == " " else ""
    return date_part, time_part


def _parse_month_anchor(date_str: str | None) -> tuple[int, int] | None:
    if not date_str:
        return None
    clean = str(date_str).strip()
    if len(clean) >= 7 and clean[:4].isdigit() and clean[4] == "-" and clean[5:7].isdigit():
        y, m = int(clean[:4]), int(clean[5:7])
        if 1 <= m <= 12:
            return y, m
    return None


def _wrap_text(text: str, width: int) -> list[str]:
    clean = " ".join(str(text or "").split())
    if not clean:
        return [""]
    lines: list[str] = []
    while len(clean) > width:
        cut = clean.rfind(" ", 0, width + 1)
        if cut <= 0:
            cut = width
        lines.append(clean[:cut].strip())
        clean = clean[cut:].strip()
    if clean:
        lines.append(clean)
    return lines


def render_calendar_pdf(
    *,
    view: str,
    title: str,
    date_str: str | None,
    events: list[dict[str, Any]],
    profiles: list[dict[str, Any]],
) -> bytes:
    """Render calendar events as a print-ready `%PDF-1.4` report (month grid + list)."""
    profile_colors = {str(p.get("id")): str(p.get("color") or "#2563eb") for p in profiles}
    silo_counts: dict[str, int] = {}
    for ev in events:
        cid = str(ev.get("calendar_id") or "user")
        silo_counts[cid] = silo_counts.get(cid, 0) + 1
    legend = [
        (profile_colors.get(cid, "#2563eb"), f"{cid} ({cnt})")
        for cid, cnt in sorted(silo_counts.items())
    ]

    month_anchor = _parse_month_anchor(date_str) if view == "month" else None
    is_month_grid = month_anchor is not None
    pw, ph = (841.89, 595.28) if is_month_grid else (595.28, 841.89)
    margin = 34.0
    pages: list[str] = []
    sub_line = f"Ansicht: {view} | {len(events)} Termine"

    if is_month_grid and month_anchor is not None:
        year, month = month_anchor
        events_by_day: dict[str, list[dict[str, Any]]] = {}
        for ev in events:
            d_part, _ = _parse_event_date_time(ev.get("start_datetime"))
            if d_part:
                events_by_day.setdefault(d_part, []).append(ev)

        weeks = pycalendar.Calendar(firstweekday=0).monthdatescalendar(year, month)
        ops = _draw_header_banner(pw, ph, margin, f"{_MONTHS_DE[month]} {year} — {title}", sub_line, legend)

        grid_top = ph - margin - 56.0
        header_h = 18.0
        grid_h = grid_top - margin - header_h
        col_w = (pw - 2 * margin) / 7.0
        row_h = grid_h / max(4, len(weeks))

        ops.append(
            f"0.12 0.16 0.23 rg {margin:.1f} {grid_top - header_h:.1f} {pw - 2 * margin:.1f} {header_h:.1f} re f"
        )
        for col_idx, wd in enumerate(_WEEKDAYS_SHORT_DE):
            cx = margin + col_idx * col_w + col_w * 0.42
            ops.append(f"1 1 1 rg BT /F2 8.5 Tf {cx:.1f} {grid_top - 12.5:.1f} Td ({wd}) Tj ET")

        max_lines_per_cell = max(2, int((row_h - 18) // 10))
        for r_idx, week in enumerate(weeks):
            cell_top = grid_top - header_h - r_idx * row_h
            cell_bottom = cell_top - row_h
            for c_idx, d_obj in enumerate(week):
                cell_x = margin + c_idx * col_w
                if d_obj.month != month:
                    ops.append(f"0.95 0.96 0.98 rg {cell_x:.1f} {cell_bottom:.1f} {col_w:.1f} {row_h:.1f} re f")
                elif d_obj.weekday() >= 5:
                    ops.append(f"0.98 0.98 0.99 rg {cell_x:.1f} {cell_bottom:.1f} {col_w:.1f} {row_h:.1f} re f")
                ops.append(f"0.78 0.82 0.88 RG 0.6 w {cell_x:.1f} {cell_bottom:.1f} {col_w:.1f} {row_h:.1f} re S")

                num_color = "0.2 0.25 0.33" if d_obj.month == month else "0.62 0.66 0.72"
                ops.append(f"{num_color} rg BT /F2 8 Tf {cell_x + 4:.1f} {cell_top - 11:.1f} Td ({d_obj.day}) Tj ET")
                if d_obj.month != month:
                    continue
                day_evs = events_by_day.get(d_obj.isoformat(), [])
                for ev_i, ev in enumerate(day_evs[:max_lines_per_cell]):
                    ey = cell_top - 22.0 - ev_i * 10.0
                    cid = str(ev.get("calendar_id") or "user")
                    r, g, b = _hex_to_rgb01(profile_colors.get(cid, "#2563eb"))
                    ops.append(f"{r} {g} {b} rg {cell_x + 3:.1f} {ey - 1:.1f} 2.5 7.5 re f")
                    _, ev_time = _parse_event_date_time(ev.get("start_datetime"))
                    t_prefix = f"{ev_time} " if ev_time else ""
                    snippet = f"{t_prefix}{ev.get('title') or ''}"[:22]
                    ops.append(
                        f"0.08 0.1 0.15 rg BT /F1 6.7 Tf {cell_x + 8:.1f} {ey:.1f} Td {pdf_encode_str(snippet)} Tj ET"
                    )
                if len(day_evs) > max_lines_per_cell:
                    extra = f"+{len(day_evs) - max_lines_per_cell} weitere"
                    ops.append(
                        f"0.35 0.4 0.48 rg BT /F1 6.3 Tf {cell_x + 8:.1f} {cell_bottom + 4.0:.1f} Td "
                        f"{pdf_encode_str(extra)} Tj ET"
                    )
        pages.append("\n".join(ops))

    if not is_month_grid or events:
        detail_title = f"{title} — Terminliste" if is_month_grid else title
        cur_ops = _draw_header_banner(pw, ph, margin, detail_title, sub_line, legend)
        y_cursor = ph - margin - 64.0
        bottom_limit = margin + 24.0

        if not events:
            cur_ops.append(
                f"0.4 0.45 0.52 rg BT /F1 10 Tf {margin:.1f} {y_cursor:.1f} Td "
                f"{pdf_encode_str('Keine Termine im gewählten Zeitraum.')} Tj ET"
            )
            pages.append("\n".join(cur_ops))
        else:
            current_grp = ""
            for ev in events:
                d_part, t_part = _parse_event_date_time(ev.get("start_datetime"))
                grp = (d_part[:7] if view in {"year", "list"} else d_part) or "Ohne Datum"
                needed = 30.0 if grp != current_grp else 15.0
                if y_cursor - needed < bottom_limit:
                    pages.append("\n".join(cur_ops))
                    cur_ops = _draw_header_banner(pw, ph, margin, detail_title, sub_line, legend)
                    y_cursor = ph - margin - 64.0
                    current_grp = ""

                if grp != current_grp:
                    current_grp = grp
                    y_cursor -= 6.0
                    grp_heading = grp
                    if len(grp) == 7 and grp[:4].isdigit() and grp[5:7].isdigit():
                        grp_heading = f"{_MONTHS_DE[int(grp[5:7])]} {grp[:4]}"
                    elif len(grp) == 10:
                        try:
                            d_obj = date.fromisoformat(grp)
                            grp_heading = f"{_WEEKDAYS_SHORT_DE[d_obj.weekday()]}, {grp}"
                        except ValueError:
                            pass
                    cur_ops.append(
                        f"0.12 0.18 0.28 rg BT /F2 9.5 Tf {margin:.1f} {y_cursor:.1f} Td "
                        f"{pdf_encode_str(grp_heading)} Tj ET"
                    )
                    y_cursor -= 14.0

                cid = str(ev.get("calendar_id") or "user")
                r, g, b = _hex_to_rgb01(profile_colors.get(cid, "#2563eb"))
                cur_ops.append(f"{r} {g} {b} rg {margin + 2:.1f} {y_cursor - 1:.1f} 3.5 8.5 re f")
                loc_part = f" @ {ev['location']}" if ev.get("location") else ""
                time_label = t_part or "--:--"
                line_str = f"{d_part or '-'}  {time_label:<5s}  [{cid}]  {ev.get('title') or ''}{loc_part}"[:112]
                cur_ops.append(
                    f"0.08 0.1 0.15 rg BT /F1 8.5 Tf {margin + 10:.1f} {y_cursor:.1f} Td "
                    f"{pdf_encode_str(line_str)} Tj ET"
                )
                y_cursor -= 13.5
            pages.append("\n".join(cur_ops))

    return assemble_pdf_document(_add_page_footers(pages, pw, margin), pw, ph)


def render_agenda_pdf(
    *,
    title: str,
    horizon: str,
    source: str,
    updated_at: str | None,
    items: list[dict[str, Any]],
) -> bytes:
    """Render filtered agenda items as a structured `%PDF-1.4` report."""
    pw, ph = 595.28, 841.89
    margin = 36.0
    horizon_counts: dict[str, int] = {"short": 0, "mid": 0, "long": 0}
    for it in items:
        hz = str(it.get("horizon") or "mid")
        if hz in horizon_counts:
            horizon_counts[hz] += 1

    legend = [
        (_HORIZON_COLORS["short"], f"Kurzfristig ({horizon_counts['short']})"),
        (_HORIZON_COLORS["mid"], f"Mittelfristig ({horizon_counts['mid']})"),
        (_HORIZON_COLORS["long"], f"Langfristig ({horizon_counts['long']})"),
    ]
    sub_line = f"Horizont: {horizon} | Quelle: {source} | {len(items)} Punkte"

    pages: list[str] = []
    cur_ops = _draw_header_banner(pw, ph, margin, title, sub_line, legend)
    y_cursor = ph - margin - 64.0
    if updated_at:
        cur_ops.append(
            f"0.38 0.43 0.52 rg BT /F1 8 Tf {margin:.1f} {y_cursor:.1f} Td "
            f"{pdf_encode_str(f'Stand: {updated_at}')} Tj ET"
        )
        y_cursor -= 16.0

    bottom_limit = margin + 28.0
    if not items:
        cur_ops.append(
            f"0.4 0.45 0.52 rg BT /F1 10 Tf {margin:.1f} {y_cursor:.1f} Td "
            f"{pdf_encode_str('Keine offenen Agenda-Punkte im gewählten Horizont.')} Tj ET"
        )
        pages.append("\n".join(cur_ops))
    else:
        for it in items:
            wrapped_title = _wrap_text(str(it.get("title") or "Ohne Titel"), 86)
            block_h = 16.0 + 12.0 * len(wrapped_title)
            if y_cursor - block_h < bottom_limit:
                pages.append("\n".join(cur_ops))
                cur_ops = _draw_header_banner(pw, ph, margin, title, sub_line, legend)
                y_cursor = ph - margin - 64.0

            hz = str(it.get("horizon") or "mid")
            r, g, b = _hex_to_rgb01(_HORIZON_COLORS.get(hz, "#38bdf8"))
            cur_ops.append(f"{r} {g} {b} rg {margin + 2:.1f} {y_cursor - 2:.1f} 4 {block_h - 4:.1f} re f")

            meta = (
                f"[{it.get('id') or '-'}]  {hz.upper()} | Prio {it.get('priority') or 'P3'} "
                f"(Gewicht {it.get('weight', 50)}) | {it.get('progress', 0)}% | "
                f"Status: {it.get('status') or 'pending'} | Kat: {it.get('category') or 'agenda'}"
            )
            if it.get("deadline"):
                meta += f" | Frist: {it['deadline']}"
            cur_ops.append(
                f"0.3 0.36 0.45 rg BT /F1 7.8 Tf {margin + 11:.1f} {y_cursor:.1f} Td "
                f"{pdf_encode_str(meta[:104])} Tj ET"
            )
            y_cursor -= 12.5
            for line in wrapped_title:
                cur_ops.append(
                    f"0.07 0.09 0.15 rg BT /F2 9.5 Tf {margin + 11:.1f} {y_cursor:.1f} Td "
                    f"{pdf_encode_str(line)} Tj ET"
                )
                y_cursor -= 12.0
            y_cursor -= 5.0
        pages.append("\n".join(cur_ops))

    return assemble_pdf_document(_add_page_footers(pages, pw, margin), pw, ph)
