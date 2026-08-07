#!/usr/bin/env python3
"""MacroMeter Phase 0 scoring engine (score_version: 0.1).

Reads the hand-rolled SM1 4FR dataset and prints ranked markdown tables:
  1. MacroScore ranking: protein-per-pound among items meeting the protein-density
     filter (default >= 35% of kcal from protein), with best applicable discount.
  2. Relaxed tier (>= 30%) so borderline items are visible.
  3. Raw protein-per-pound leaderboard (no density filter) for comparison.

Usage: python3 scripts/phase0_rank.py [--min-share 0.35] [--no-discounts]
"""
import argparse
import csv
import pathlib

DATA = pathlib.Path(__file__).resolve().parent.parent / "data" / "phase0"


def load(name):
    with open(DATA / name, newline="") as f:
        return list(csv.DictReader(f))


def protein_share(item):
    kcal = float(item["kcal"])
    return (float(item["protein_g"]) * 4) / kcal if kcal else 0.0


def best_discount(item, rules, eligibility):
    """Single best applicable discount (UK offers rarely stack)."""
    best = None
    for r in rules:
        if r["chain_id"] != item["chain_id"] or r["type"] != "percent" or not r["value"]:
            continue
        conds = set(filter(None, r["conditions"].split(";")))
        if "first_order" in conds and not eligibility.get("first_order", False):
            continue
        if any(c.startswith("student_platform") for c in conds) and not eligibility.get("student", False):
            continue
        if r["scope"] == "item" and r["item_matcher"] != "*" \
                and r["item_matcher"].lower() not in item["item"].lower():
            continue
        pct = float(r["value"])
        if best is None or pct > best[0]:
            best = (pct, r["rule_id"])
    return best


def rank(items, rules, chains, min_share, use_discounts, eligibility):
    halal = {c["chain_id"]: c["halal_status"] for c in chains}
    out = []
    for it in items:
        if not it["price_gbp"]:
            continue
        price = float(it["price_gbp"])
        disc = best_discount(it, rules, eligibility) if use_discounts else None
        final = price * (1 - disc[0] / 100) if disc else price
        share = protein_share(it)
        if share < min_share:
            continue
        out.append(dict(
            item=it["item"], chain=it["chain_id"], kcal=float(it["kcal"]),
            protein=float(it["protein_g"]), share=share, price=price, final=final,
            disc=disc[1] if disc else "", score=float(it["protein_g"]) / final,
            halal=halal.get(it["chain_id"], "?"),
            conf=it["nutrition_confidence"],
        ))
    return sorted(out, key=lambda r: r["score"], reverse=True)


def table(rows, n=15):
    print("| # | Item | Chain | Protein | kcal | P% kcal | Price | Final | g protein/£ | Halal | Conf |")
    print("|--:|------|-------|--------:|-----:|--------:|------:|------:|------------:|-------|------|")
    for i, r in enumerate(rows[:n], 1):
        disc = f" ({r['disc']})" if r["disc"] else ""
        print(f"| {i} | {r['item']} | {r['chain']} | {r['protein']:.0f}g | {r['kcal']:.0f} "
              f"| {r['share']*100:.0f}% | £{r['price']:.2f} | £{r['final']:.2f}{disc} "
              f"| **{r['score']:.1f}** | {r['halal']} | {r['conf']} |")
    print()


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--min-share", type=float, default=0.35)
    ap.add_argument("--no-discounts", action="store_true")
    args = ap.parse_args()

    items, rules, chains = load("menu_items.csv"), load("discounts.csv"), load("chains.csv")
    eligibility = {"student": True, "first_order": True}  # Phase 0: assume max eligibility
    use_disc = not args.no_discounts

    print(f"### MacroScore ranking — protein >= {args.min_share:.0%} of calories\n")
    table(rank(items, rules, chains, args.min_share, use_disc, eligibility))

    print("### Relaxed tier — protein >= 30% of calories\n")
    table(rank(items, rules, chains, 0.30, use_disc, eligibility))

    print("### Raw protein-per-£ leaderboard (no density filter)\n")
    table(rank(items, rules, chains, 0.0, use_disc, eligibility), n=20)


if __name__ == "__main__":
    main()
