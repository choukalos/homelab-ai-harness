#!/usr/bin/env python3
"""Deterministic dice for TTRPG play.

GURPS uses 3d6 "roll-under": a roll succeeds if the 3d6 total is <= the target
number (a skill, attribute, or secondary characteristic). All rolls are seeded
so they are reproducible and auditable — no LLM-hallucinated dice.

Usage (CLI):
    dice.py 3d6 --seed 42                 # roll 3d6, print total
    dice.py 3d6 --seed 42 --under 12      # roll 3d6, roll-under 12
    dice.py 2d10 --seed 7                 # roll 2d10
    dice.py 3d6 --seed 42 --modifier -2   # roll 3d6, add modifier
"""
import argparse
import random
import re
import sys


def parse_notation(expr: str) -> tuple[int, int]:
    """Parse dice notation like '3d6' or '2d10' -> (count, sides)."""
    m = re.fullmatch(r"\s*(\d+)\s*d\s*(\d+)\s*", expr, re.IGNORECASE)
    if not m:
        raise ValueError(f"bad dice notation: {expr!r} (expected like '3d6')")
    count, sides = int(m.group(1)), int(m.group(2))
    if count < 1 or sides < 2:
        raise ValueError(f"bad dice notation: {expr!r}")
    return count, sides


def roll_dice(expr: str, seed: int) -> dict:
    """Roll the dice and return the breakdown + total.

    Returns: {"notation", "seed", "rolls": [...], "total": int}
    """
    count, sides = parse_notation(expr)
    rng = random.Random(seed)
    rolls = [rng.randint(1, sides) for _ in range(count)]
    return {
        "notation": expr,
        "seed": seed,
        "rolls": rolls,
        "total": sum(rolls),
    }


def roll_under(expr: str, target: int, seed: int, modifier: int = 0) -> dict:
    """Roll the dice and check roll-under `target` (with an optional modifier).

    GURPS convention: success if (total + modifier) <= target.
    Returns: roll_dice fields + {"target", "modifier", "effective", "success"}
    """
    r = roll_dice(expr, seed)
    effective = r["total"] + modifier
    r["target"] = target
    r["modifier"] = modifier
    r["effective"] = effective
    r["success"] = effective <= target
    return r


def main():
    ap = argparse.ArgumentParser(description="Deterministic dice for TTRPG play.")
    ap.add_argument("notation", help="dice notation, e.g. 3d6, 2d10")
    ap.add_argument("--seed", type=int, default=0, help="seed (default 0)")
    ap.add_argument("--under", type=int, default=None,
                    help="roll-under target (GURPS: success if total <= target)")
    ap.add_argument("--modifier", type=int, default=0,
                    help="modifier added to the total before comparing")
    args = ap.parse_args()

    try:
        if args.under is None:
            result = roll_dice(args.notation, args.seed)
        else:
            result = roll_under(args.notation, args.under, args.seed,
                                args.modifier)
    except ValueError as e:
        print(f"error: {e}", file=sys.stderr)
        return 2

    print(f"{result['notation']} (seed={result['seed']}) = "
          f"{result['rolls']} -> {result['total']}")
    if "success" in result:
        status = "SUCCESS" if result["success"] else "FAIL"
        mod = f" (modifier {result['modifier']:+d} -> {result['effective']})" \
            if result.get("modifier") else ""
        print(f"  roll-under {result['target']}{mod}: {status}")
    return 0


if __name__ == "__main__":
    sys.exit(main())