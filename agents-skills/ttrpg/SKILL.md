---
name: ttrpg
description: Run a TTRPG session from a game_system digest — generate characters, adjudicate combat, social/skill tests, healing/recovery, and leveling. Uses the digest for the rules and deterministic scripts (dice.py, state.py) for rolls and derived stats, so nothing is LLM-hallucinated.
---

# TTRPG (game applier)

Runs a tabletop RPG session *from a `game_system` digest*. The digest is the
rules source (grounded in the actual rulebook); the scripts handle the
deterministic parts (dice, derived stats, point validation) so rolls and
numbers are reproducible and auditable. The agent handles the narrative and
adjudication.

**Prerequisite:** a `game_system` digest exists (build one with `/skill:digest`
if you don't have one). Currently tuned for GURPS; the pattern generalizes to
other systems by swapping the digest + script constants.

## When to use
- "Generate a character" / "make me a GURPS hero".
- "Run combat" / "adjudicate this fight".
- "Does the character succeed at <skill>?" / social interaction checks.
- "How does the character recover?" / healing, resting, fatigue.
- "Level up" / improve skills / spend bonus points.

## Prerequisites
- A `game_system` digest (via `kb_digest_get(slug, "game_system")`).
- The scripts in this skill's `scripts/` dir:
  - `dice.py` — deterministic dice (3d6, roll-under, modifiers).
  - `state.py` — derived stats, point-buy validation, HP tracking.

## Workflow

### 1. Load the rules
`kb_digest_get(slug, "game_system")` → the digest. Use its sections for the
rules (attribute costs, derived formulas, combat, skills, recovery, tables).
If a rule you need isn't in the digest, read the source page via
`kb_get_pages` and note the gap (the digest is lossy).

### 2. Character generation
1. Pick a concept + starting attributes (ST/DX/IQ/HT).
2. `state.py derive --st .. --dx .. --iq .. --ht ..` → HP, Will, Per, FP, BL,
   BS, Dodge, Move, Dmg (all from the digest's formulas).
3. Choose skills; `state.py validate --st .. --dx .. --iq .. --ht ..
   --budget <N> --skills "<costs>"` → confirms the build fits the budget
   (uses the digest's attribute + skill costs).
4. If using 3d6 instead of point-buy, `dice.py 3d6 --seed <s>` per attribute.

### 3. Combat
1. Initiative: order by Dodge (digest's turn order).
2. Attack: `dice.py 3d6 --seed <s> --under <defense>` → hit/miss (defense =
   the target's Dodge or parry, from the digest).
3. On a hit: apply damage from the digest's damage table / weapon.
   `state.py hit --hp <N> --damage <N>` → new HP + status.
4. Repeat per round; track HP/FP.

### 4. Social / skill tests
Roll under the relevant skill (or attribute) value:
`dice.py 3d6 --seed <s> --under <skill_value>`. Use the digest's skill list
and defaults for what the character can attempt.

### 5. Healing / recovery
Use the digest's recovery rules (HP/FP recovery, resting, injury effects).
`state.py hit` for damage; track FP for fatigue. If the digest lacks recovery
detail, read the source pages (e.g. GURPS pp. 418-427).

### 6. Leveling / improvement
Use the digest's improvement rules (skill cost table for raising skills,
bonus-point spending). `state.py validate` to confirm a re-buy fits.

## How to use the scripts
```bash
# derive stats
python3 scripts/state.py derive --st 13 --dx 12 --iq 10 --ht 11
# validate a 100-pt build with 10 skills @ 2 pts
python3 scripts/state.py validate --st 13 --dx 12 --iq 10 --ht 11 \
    --budget 100 --skills "2,2,2,2,2,2,2,2,2,2"
# roll 3d6, roll-under 8
python3 scripts/dice.py 3d6 --seed 42 --under 8
# apply 9 damage to 13 HP
python3 scripts/state.py hit --hp 13 --damage 9
```
Pass a `--seed` for reproducible rolls (record it in the session log). The
agent chooses seeds or uses a per-scene seed; the scripts never invent
numbers.

## Notes
- **Dice and derived stats are deterministic** (scripts) — the LLM never
  rolls or computes them. This is the whole point: no hallucinated 3d6.
- **The digest is the rules source.** If it's missing a rule, read the source
  page and (optionally) re-digest to capture it.
- **Narrative is the agent's job** — the scripts give numbers; you run the
  scene, describe outcomes, and adjudicate edge cases using the digest.
- **GURPS-specific for now.** To support another system, add its digest +
  adjust the script constants (attribute costs, derived formulas, damage
  table). Star Wars is the next candidate.