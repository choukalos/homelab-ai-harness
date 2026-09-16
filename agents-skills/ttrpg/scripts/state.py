#!/usr/bin/env python3
"""GURPS character state: derived stats, point-buy validation, HP tracking.

The derived-stat formulas and point costs come from the GURPS game_system
digest (grounded in GURPS 4e Revised, pp. 24-28, 180). This makes the
deterministic parts of character creation and combat reproducible — the agent
supplies the character's attributes/skills; this script computes the rest.

Usage (CLI):
    state.py derive --st 13 --dx 12 --iq 10 --ht 11
    state.py validate --st 13 --dx 12 --iq 10 --ht 11 --budget 100 \
        --skills "2,2,2,2,2,2,2,2,2,2"
    state.py hit --hp 13 --damage 9
"""
import argparse
import json
import sys

# ---- GURPS rules (from the game_system digest) ----
ATTR_COST = {"ST": 10, "DX": 20, "IQ": 20, "HT": 10}  # pts/level above 10 (p.24)
BASE = 10

# Damage table (ST -> (thrust, swing)) from p.26
DAMAGE = {
    1: ("1d-6", "1d-5"), 2: ("1d-6", "1d-5"), 3: ("1d-5", "1d-4"),
    4: ("1d-5", "1d-4"), 5: ("1d-4", "1d-3"), 6: ("1d-4", "1d-3"),
    7: ("1d-3", "1d-2"), 8: ("1d-3", "1d-2"), 9: ("1d-2", "1d-1"),
    10: ("1d-2", "1d"), 11: ("1d-1", "1d+1"), 12: ("1d-1", "1d+2"),
    13: ("1d", "2d-1"), 14: ("1d", "2d"), 15: ("1d+1", "2d+1"),
    16: ("1d+1", "2d+2"), 17: ("1d+2", "3d-1"), 18: ("1d+2", "3d"),
    19: ("2d-1", "3d+1"), 20: ("2d-1", "3d+2"), 21: ("2d", "4d-1"),
    22: ("2d", "4d"), 23: ("2d+1", "4d+1"), 24: ("2d+1", "4d+2"),
    25: ("2d+2", "5d-1"), 26: ("2d+2", "5d"), 27: ("3d-1", "5d+1"),
    28: ("3d-1", "5d+1"), 29: ("3d", "5d+2"), 30: ("3d", "5d+2"),
    31: ("3d+1", "6d-1"), 32: ("3d+1", "6d-1"), 33: ("3d+2", "6d"),
    34: ("3d+2", "6d"), 35: ("4d-1", "6d+1"), 36: ("4d-1", "6d+1"),
    37: ("4d", "6d+2"), 38: ("4d", "6d+2"), 39: ("4d+1", "7d-1"),
    40: ("4d+1", "7d-1"), 45: ("5d", "7d+1"), 50: ("5d+2", "8d-1"),
    55: ("6d", "8d+1"), 60: ("7d-1", "9d"), 65: ("7d+1", "9d+2"),
    70: ("8d", "10d"), 75: ("8d+2", "10d+2"), 80: ("9d", "11d"),
    85: ("9d+2", "11d+2"), 90: ("10d", "12d"), 95: ("10d+2", "12d+2"),
    100: ("11d", "13d"),
}


def attr_cost(value: int, attr: str) -> int:
    """Points to buy an attribute at `value` (10 is free)."""
    return (value - BASE) * ATTR_COST[attr]


def damage_for_st(st: int) -> tuple[str, str]:
    """(thrust, swing) basic damage for a given ST (nearest table row)."""
    if st in DAMAGE:
        return DAMAGE[st]
    # GURPS table has gaps above 40; use the nearest defined ST.
    keys = sorted(DAMAGE)
    nearest = min(keys, key=lambda k: abs(k - st))
    return DAMAGE[nearest]


def derive(st: int, dx: int, iq: int, ht: int) -> dict:
    """Compute all secondary characteristics from raw attributes (p.26-28)."""
    hp = st
    will = iq            # Revised edition: Will = IQ
    per = iq
    fp = ht
    bl = (st * st) / 5
    if bl >= 10:
        bl = round(bl)
    bs = (ht + dx) / 4   # do NOT round (p.27)
    dodge = int(bs) + 3  # drop fraction (p.27)
    move = int(bs)       # drop fraction (p.27)
    thrust, swing = damage_for_st(st)
    return {
        "HP": hp, "Will": will, "Per": per, "FP": fp,
        "BL": bl, "BS": bs, "Dodge": dodge, "Move": move,
        "Dmg": f"{thrust}/{swing}",
    }


def validate(st: int, dx: int, iq: int, ht: int, budget: int,
             skill_points: list[int]) -> dict:
    """Validate a point-buy build against a budget."""
    attr_spend = {
        "ST": attr_cost(st, "ST"),
        "DX": attr_cost(dx, "DX"),
        "IQ": attr_cost(iq, "IQ"),
        "HT": attr_cost(ht, "HT"),
    }
    skill_spend = sum(skill_points)
    total = sum(attr_spend.values()) + skill_spend
    remaining = budget - total
    return {
        "attributes": {"ST": st, "DX": dx, "IQ": iq, "HT": ht},
        "attribute_spend": attr_spend,
        "skill_spend": skill_spend,
        "n_skills": len(skill_points),
        "total_spent": total,
        "budget": budget,
        "remaining": remaining,
        "valid": remaining >= 0,
        "derived": derive(st, dx, iq, ht),
    }


def apply_damage(hp: int, damage: int) -> dict:
    """Apply damage to HP and report the resulting status."""
    new_hp = hp - damage
    if new_hp <= -hp:
        status = "dead"
    elif new_hp <= 0:
        status = "unconscious"
    elif new_hp < hp:
        status = "injured"
    else:
        status = "ok"
    return {"hp_before": hp, "damage": damage, "hp_after": new_hp,
            "status": status}


def main():
    ap = argparse.ArgumentParser(description="GURPS character state.")
    sub = ap.add_subparsers(dest="cmd", required=True)

    d = sub.add_parser("derive", help="compute derived stats")
    for a in ("st", "dx", "iq", "ht"):
        d.add_argument(f"--{a}", type=int, required=True)

    v = sub.add_parser("validate", help="validate a point-buy build")
    for a in ("st", "dx", "iq", "ht"):
        v.add_argument(f"--{a}", type=int, required=True)
    v.add_argument("--budget", type=int, required=True)
    v.add_argument("--skills", default="",
                   help="comma-separated skill point costs")

    h = sub.add_parser("hit", help="apply damage to HP")
    h.add_argument("--hp", type=int, required=True)
    h.add_argument("--damage", type=int, required=True)

    args = ap.parse_args()

    if args.cmd == "derive":
        out = derive(args.st, args.dx, args.iq, args.ht)
    elif args.cmd == "validate":
        skills = [int(x) for x in args.skills.split(",") if x.strip()]
        out = validate(args.st, args.dx, args.iq, args.ht, args.budget, skills)
    elif args.cmd == "hit":
        out = apply_damage(args.hp, args.damage)
    else:
        ap.error("unknown command")
        return 2
    print(json.dumps(out, indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())