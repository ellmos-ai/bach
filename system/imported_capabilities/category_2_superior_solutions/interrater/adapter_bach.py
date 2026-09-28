# -*- coding: utf-8 -*-
# SPDX-License-Identifier: MIT
"""
Bach Adapter for Inter-Rater Reliability & Rater Race (from NemoFold).

Provides statistical comparison (Cohen's Kappa & raw agreement) between multiple LLM outputs
or autonomous subagent decisions on identical task sets, replacing naive text diffs.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Dict, List, Optional, Tuple

from .interrater import Agreement, CellDiff, Coding, InterraterReport


def compute_model_agreement(
    model_a_name: str,
    model_a_decisions: Dict[str, str],
    model_b_name: str,
    model_b_decisions: Dict[str, str],
) -> InterraterReport:
    """
    Computes rigorous inter-rater agreement statistics between two model runs.
    
    Args:
        model_a_name: Name/identity of first model/rater.
        model_a_decisions: Map of item_id -> classification/decision code.
        model_b_name: Name/identity of second model/rater.
        model_b_decisions: Map of item_id -> classification/decision code.
    """
    all_keys = sorted(set(model_a_decisions.keys()) & set(model_b_decisions.keys()))
    only_in_a = tuple(sorted(set(model_a_decisions.keys()) - set(model_b_decisions.keys())))
    only_in_b = tuple(sorted(set(model_b_decisions.keys()) - set(model_a_decisions.keys())))

    cells: List[CellDiff] = []
    agreed_count = 0
    cat_counts_a: Dict[str, int] = {}
    cat_counts_b: Dict[str, int] = {}

    for k in all_keys:
        code_a = str(model_a_decisions[k])
        code_b = str(model_b_decisions[k])
        diff = CellDiff(item_id=k, code_a=code_a, code_b=code_b)
        cells.append(diff)
        if diff.agree:
            agreed_count += 1
        cat_counts_a[code_a] = cat_counts_a.get(code_a, 0) + 1
        cat_counts_b[code_b] = cat_counts_b.get(code_b, 0) + 1

    total_items = len(all_keys)
    if total_items == 0:
        agreement = Agreement(
            items=0, agreed=0, percent=0.0, kappa=None, kappa_note="no overlapping items"
        )
    else:
        percent = (agreed_count / total_items) * 100.0

        # Calculate Cohen's Kappa
        all_categories = sorted(set(cat_counts_a.keys()) | set(cat_counts_b.keys()))
        pe = sum(
            (cat_counts_a.get(c, 0) / total_items) * (cat_counts_b.get(c, 0) / total_items)
            for c in all_categories
        )
        po = agreed_count / total_items

        if pe >= 1.0:
            kappa = None
            kappa_note = "undefined (deterministic identical single category)"
        elif 1.0 - pe == 0:
            kappa = None
            kappa_note = "undefined (denominator is zero)"
        else:
            kappa = (po - pe) / (1.0 - pe)
            kappa_note = "computed"

        agreement = Agreement(
            items=total_items,
            agreed=agreed_count,
            percent=round(percent, 2),
            kappa=round(kappa, 4) if kappa is not None else None,
            kappa_note=kappa_note,
        )

    return InterraterReport(
        rater_a=model_a_name,
        rater_b=model_b_name,
        cells=tuple(cells),
        agreement=agreement,
        only_in_a=only_in_a,
        only_in_b=only_in_b,
    )
