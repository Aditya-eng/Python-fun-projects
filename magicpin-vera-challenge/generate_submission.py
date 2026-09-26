#!/usr/bin/env python3
"""
Builds submission.jsonl — the 30-line deliverable from challenge-brief.md §7.2.

Reads the expanded local dataset (dataset/expanded/, produced by
`python dataset/generate_dataset.py --out dataset/expanded`) and the 30
canonical test pairs, runs each through the same composer the live bot uses,
and writes one JSON line per test_id.

Usage:
    python dataset/generate_dataset.py --out dataset/expanded
    python generate_submission.py
"""

from __future__ import annotations

import json
from pathlib import Path

from composer import compose
from facts import build_fact_pack
from validators import validate_and_repair

ROOT = Path(__file__).parent
DATA = ROOT / "dataset" / "expanded"


def _load(path: Path) -> dict:
    return json.loads(path.read_text())


def main() -> None:
    test_pairs_path = DATA / "test_pairs.json"
    if not test_pairs_path.exists():
        raise SystemExit(
            f"Missing {test_pairs_path}. Run: python dataset/generate_dataset.py --out dataset/expanded"
        )

    pairs = _load(test_pairs_path)["pairs"]
    categories = {p.stem: _load(p) for p in (DATA / "categories").glob("*.json")}
    merchants = {p.stem: _load(p) for p in (DATA / "merchants").glob("*.json")}
    customers = {p.stem: _load(p) for p in (DATA / "customers").glob("*.json")}
    triggers = {p.stem: _load(p) for p in (DATA / "triggers").glob("*.json")}

    lines = []
    for pair in pairs:
        test_id = pair["test_id"]
        merchant_id = pair["merchant_id"]
        trigger_id = pair["trigger_id"]
        customer_id = pair.get("customer_id")

        merchant = next((m for k, m in merchants.items() if k.startswith(merchant_id) or m.get("merchant_id") == merchant_id), None)
        trigger = next((t for k, t in triggers.items() if k.startswith(trigger_id) or t.get("id") == trigger_id), None)
        customer = None
        if customer_id:
            customer = next((c for k, c in customers.items() if k.startswith(customer_id) or c.get("customer_id") == customer_id), None)

        if merchant is None or trigger is None:
            print(f"WARN {test_id}: could not resolve merchant={merchant_id} trigger={trigger_id}; skipping")
            continue

        category = categories.get(merchant.get("category_slug"))

        composed = compose(category, merchant, trigger, customer)
        fp = build_fact_pack(category, merchant, trigger, customer)
        composed = validate_and_repair(composed, fp, category)

        lines.append(json.dumps({
            "test_id": test_id,
            "body": composed["body"],
            "cta": composed["cta"],
            "send_as": composed["send_as"],
            "suppression_key": composed["suppression_key"],
            "rationale": composed["rationale"],
        }, ensure_ascii=False))

    out_path = ROOT / "submission.jsonl"
    out_path.write_text("\n".join(lines) + "\n")
    print(f"Wrote {len(lines)} lines to {out_path}")


if __name__ == "__main__":
    main()
