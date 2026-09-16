# DIGEST — game_system

<!-- Fill every section. Each `## ` section becomes a searchable fact.
     Every load-bearing claim gets a page_ref (PDF page number).
     Capture rules as formulas/tables, not prose. The character-creation
     METHOD and its exact costs are the most load-bearing claims. -->

# source: <doc path or title>
# type: game_system | edition: <e.g. "4e Revised"> | pages: <n>

## Downstream Task
<!-- What this digest must enable. e.g.: point-buy a valid character within a
     budget; compute derived stats; adjudicate combat and skill rolls; DM a
     game. This focuses the digest on the right structure. -->

## Overview
<!-- 3-6 lines: what the game is, the core fantasy, scope of this digest
     (which parts of the book it covers), and the edition (critical — rules
     change between editions; e.g. GURPS 4e vs 4e Revised). -->

## Core Mechanics
<!-- The core resolution loop. Capture the EXACT procedure. -->
- resolution: <e.g. 3d6 ≤ skill = success; 3×1/3×6 = critical/fumble>
- turn_order: <e.g. by Dodge, tie → higher Basic Speed>
- <other core loops (movement, morale, etc.)>

## Attributes
<!-- Table of the core attributes. For each: meaning, how it's set, and any
     derived stats. page_ref the attribute-creation page. -->
| Attr | Meaning | Set by | Derived | page_ref |
|------|---------|--------|---------|----------|
| ST   | strength | point-buy / 3d6 | HP, BL, Dmg | p.X |
| DX   | agility  | point-buy / 3d6 | BS, Dmg | p.X |
| IQ   | intellect| point-buy / 3d6 | Will, Per | p.X |
| HT   | health   | point-buy / 3d6 | FP | p.X |

## Character Creation
<!-- THE load-bearing section. Capture the actual method (point-buy vs 3d6)
     and the EXACT costs. A wrong method = a wrong character, even if the
     derived stats are internally consistent. -->
- method: <point-buy (100-pt budget) / 3d6 / ...>
- budget: <e.g. 100 points = "normal person">
- attribute_costs:
  | Attr | cost/level above 10 | page_ref |
  |------|---------------------|----------|
  | ST   | 10                  | p.X |
  | DX   | 20                  | p.X |
  | IQ   | 20                  | p.X |
  | HT   | 10                  | p.X |
- skill_costs: <e.g. 2 pts = Attribute+0 (Average); 4 = +1; ...>
- steps: <ordered procedure to build a character>

## Derived Stats
<!-- Every derived stat as an EXACT formula. page_ref each. -->
- HP = <ST> (p.X)
- Will = <IQ> (p.X)   <!-- note: Revised edition sets Will=IQ, not IQ/2 -->
- Per = <IQ> (p.X)
- FP = <HT> (p.X)
- BL = <(ST^2)/5 lbs> (p.X)
- Basic Speed = <(HT+DX)/4, no rounding> (p.X)
- Dodge = <int(BS)+3> (p.X)
- Move = <int(BS)> (p.X)
- Damage (unarmed) = <table by ST> (p.X)

## Combat
<!-- Turn order, attacks, damage, defense. Exact procedure. -->
- turn_order: <...>
- attack: <...>
- defense: <Dodge / parry / block>
- damage: <how damage is applied, injury table>

## Skills
<!-- Skill categories, how they're learned, point costs. -->
- categories: <...>
- point_costs: <...>

## Key Tables
<!-- The tables the downstream task depends on (damage, injury, etc.), with
     page_refs so they can be re-read. -->
- <table name>: p.X-Y

## gotchas
<!-- Version-specific or easy-to-get-wrong details. -->
- <gotcha>

## verification
<!-- Independent checks for the load-bearing claims. The key check: build a
     character the ACTUAL way the system works (the real method + real costs)
     and confirm it's valid — not just that derived stats are consistent. -->
- claim: <character-creation method + costs> → check: <build a character,
  confirm budget/costs/derived stats>
- claim: <derived-stat formulas> → check: <recompute on a sample character>

## page_refs
<!-- Where each section was grounded. -->
- <section>: p.X-Y