---
name: one-page-arcade-3d
description: Build 3D arcade games as a single self-contained HTML file (inlined Three.js r160, WebGL, flat-shaded low-poly procedural geometry, chase cameras) plus the pseudo-3D perspective-on-canvas pattern, with the WebGL context-loss hardening Safari needs. Use when the user wants a 3D/WebGL arcade game or a Star Wars-style perspective game as one file.
---

# One-Page Arcade 3D — single-file HTML 3D arcade games

Each game is **one self-contained `.html` file** with real-time 3D — an inlined
**Three.js r160 UMD** (~670KB, no CDN, no network requests) or the **pseudo-3D
perspective-on-canvas** pattern (Star Wars trench run: true 3D projection math on a 2D
canvas, no WebGL). Plus the usual house conventions — inline CSS (HUD/overlay),
procedural WebAudio, `localStorage` hi-score, `?shot=1` autopilot. Reference library
(Mac): `~/Code/one-page-arcade/` — WebGL games (zombie-city, skiing/Alpine Rush,
battlezone, elite, outrun), `star-wars.html` (pseudo-3D), per-game `*-build-plan.md`
(battlezone, elite, outrun, skiing, star-wars), `*-parts/` dirs, and
`skiing-gl-crash-investigation.md` (the WebGL black-screen root-cause writeup). A
ready-made LLM prompt template for 3D games lives at
`~/Code/example_3d_game_prompt.txt.save`.

## When to use

- A 3D/WebGL arcade game as a single HTML file (tank battle, space flight, driving,
  first-person zombie survival, downhill ski).
- A perspective "3D-feel" game that must stay a plain 2D canvas (no WebGL requirement —
  works everywhere, including Safari).
- Fix / QA an existing one-page 3D game (jump to **QA** and **WebGL crash patterns**).

For flat 2D canvas games (pac-man, tetris, moon-patrol, …) use the `one-page-arcade-2d`
skill instead.

## Choosing the 3D approach

| Approach | Use when | Example |
|---|---|---|
| **WebGL / Three.js r160 inlined** | real 3D — free camera, 3D physics, 3D collision | battlezone, elite, outrun, skiing, zombie-city |
| **Pseudo-3D on 2D canvas** | a single corridor/road in perspective; must run without WebGL | star-wars trench run |

## Workflow — plan → parts → assemble → QA → publish

### 1. Plan (`<game>-build-plan.md`)

Goal, look (palette/fog/shading), exact design numbers (physics, enemy types with
speed/hp/dmg/radius/points/fire-rate, waves, scoring, lives, states), part-file table,
assembly command, test plan. If the game is LLM-drafted, brief it with the 3D prompt
template (`example_3d_game_prompt.txt.save` pattern: single-file HTML, blocky
retro-future flat-shaded aesthetic, chase camera, bounding-box collision, win target,
HUD overlay) — then **inline the Three.js UMD** to make it self-contained (a CDN
reference breaks self-containment; the elite rebuild fixed exactly that) and add the
missing house conventions (title/pause/hi-score/sound/crash-overlay/tests).

### 2. Parts — WebGL games (the 8-part structure)

All five WebGL games share this layout in `<game>-parts/`:

| # | File | Contents |
|---|------|----------|
| 1 | `01-head.html` | `<!DOCTYPE>` … `<style>` (reset, `#hud`, `#overlay`, color classes) … `</head>` |
| 2 | `02-body.html` | `#hud` (score/hi/wave/lives/health), `#overlay/#msgBox`, `#dbg` status box, `canvas#c` |
| 3 | `03-three-lib.js` | **`cp` from `skiing-parts/03-three-lib.js`** — the Three.js r160 UMD `<script>` block (~670KB). Do NOT hand-write. |
| 4 | `04-js-setup.js` | `<script>` open; `fatal()`; **renderer setup**; **context-loss resilience**; scene/camera/lights/fog; world geometry; object pools; `resize()` |
| 5 | `05-js-core.js` | audio (`ensureAudio` + `playSound` switch); constants; helpers (`R`/`C`/`L`/`rotToward`/`angDiff`); **ALL state vars**; `initWorld()` |
| 6 | `06-js-update.js` | `update()` — player physics, enemy AI, projectiles, collisions, waves, scoring, state machine |
| 7 | `07-js-draw.js` | `draw()` — context-health poll; sync THREE meshes from state; camera follow/shake; HUD; `dbg()` |
| 8 | `08-js-main.js` | input (keyboard + mouse/pointer lock), `initGame()`, `showMsg`/`hideMsg`, `shotPilot()`, `loop()`, `</script></body></html>` close |

Assembly: `cat 01…08 > ../<game>.html`, then the standard node syntax check (same one-liner
as the 2D skill — check every `<script>` block).

**Renderer setup (04-js-setup.js) — proven rules:**

```js
renderer = new THREE.WebGLRenderer({ canvas: c, antialias: false }); // let Three.js create the context (webgl2 → webgl1 fallback); pre-creating a context on the canvas BREAKS that fallback
renderer.setPixelRatio(Math.min(window.devicePixelRatio || 1, 1.0)); // cap 1.0 keeps the framebuffer small
if (THREE.SRGBColorSpace) renderer.outputColorSpace = THREE.SRGBColorSpace;
```

**Context-loss resilience (mandatory — see WebGL crash patterns):** `webglcontextlost`
listener (`ev.preventDefault()` → `markContextLost()`), per-frame
`renderer.getContext().isContextLost()` poll in `draw()`, `forceContextRestore()` nudge
after 1.5s, **GRAPHICS CRASHED** overlay after 4s (RELOAD button + "quit Safari (Cmd+Q) →
reboot + macOS updates" instructions), `webglcontextrestored` clears it. Wrap
`renderer.render()` in try/catch — transient errors during loss/restore transitions are
expected; the poll + handler cover the real failure.

**3D conventions:**

- **Axes:** X/Z ground plane, Y up; `angle` = heading, forward = `(cos a, sin a)` in
  (x,z). Flight: yaw/pitch/roll in **YXZ order** — forward =
  `(sinψ·cosθ, −sinθ, cosψ·cosθ)`; roll auto-levels; **coast thrust = 0** (the "gentle
  coast" bug: non-zero coast thrust means the ship never stops) + drag
  `vel *= pow(0.98, dt*60)`.
- **Geometry:** flat-shaded low-poly procedural — `Box/Cylinder/Cone/Plane/Icosahedron`
  primitives, `MeshLambertMaterial`/`MeshPhongMaterial` with `flatShading: true`, emissive
  accent materials. No external models/textures.
- **Atmosphere:** dark background + `THREE.Fog` for depth; ambient + one directional
  light; a faint `GridHelper` or starfield.
- **Performance:** object **pools** for shells/explosions/particles (no per-frame
  allocation); `antialias:false` + pixelRatio cap 1.0; keep `draw()` to cheap state →
  mesh sync.
- **Camera:** chase camera — position = player − forward·back + up·height, `lookAt` the
  player (or orbit on the title screen); add shake offsets.
- **Testability split (important):** `update()` is **THREE-free** (plain JS math) and
  `draw()` reads state and updates THREE objects — this is what keeps the Node tests
  (deep THREE mock) meaningful.
- **Controls:** keyboard for flight/drive (W/S/A/D + arrows; Shift thrust / Ctrl brake
  for flight; Space fire; `P` pause; `Enter`/`Space` start), mouse + pointer lock (or
  Q/E) for independent turret/aim axes. Optional touch like the 2D skill.
- **`?shot=1`** autopilot (`shotPilot()`) for headless screenshots + bot tests.

### 3. Parts — pseudo-3D on canvas (star-wars pattern)

For a corridor/road in perspective without WebGL, use a **pinhole camera** on the 2D
canvas (full model in `star-wars-plan.md`):

- Camera at origin looking down **+Z** (into the screen); `horizonY = H()*0.42`
  (vanishing point), `SC = H()*1.15` (zoom).
- Project world `(x, y, z)` (z = depth ahead): `sx = W()/2 + (x/z)*SC`,
  `sy = horizonY + (y/z)*SC`, `size = baseSize * (SC/z)`.
- Depth range `Z_NEAR` (gun/camera plane) … `Z_FAR` (spawn); objects advance `z -= speed`
  each frame; walls/floor/ceiling are filled perspective polygons that spread as z shrinks.
- **Speed effect:** scrolling rungs/panel lines — a `dist` counter advances by `speed`;
  rungs drawn at world intervals `k*300`, projected at `z = k*300 − dist`.
- **Hit detection in screen space:** when a projectile reaches the crosshair, hit any
  object whose projected screen position is within ~30px of it; player is hit if the
  crosshair is within ~26px of an incoming bolt's fire-time target (dodge by moving).
- Same house conventions otherwise (CRT/HUD/overlay, WebAudio, hi-score, part files,
  `?shot=1`, node tests — no THREE mock needed).

### 4. QA (headless, node)

Same harness pattern as the 2D skill (stubbed DOM/canvas, rAF driver, autopilot), plus:

- **Deep THREE mock** — a Proxy that returns a fresh mock for any property/get/construct
  (see `battlezone-parts/tests/crash-overlay-test.js`); this is why the THREE-free
  `update()` split matters.
- **smoke-test.js** — state machine, physics (positions finite, in arena), collisions,
  scoring, waves, respawn.
- **bot-test.js** — autopilot (`?shot=1`) many frames / multiple waves; no NaN, entity
  caps hold, no crash.
- **crash-overlay-test.js** (WebGL games) — context lost (via the event path AND the
  `draw()` health-poll path) → restore nudge → GRAPHICS CRASHED overlay with reload
  button; restored → cleared.
- Bug reports: same lane-based QA plan as the 2D skill (visual-render /
  gameplay-physics / flow-logic / runtime-robustness), sequential fixes in the part
  files, reassemble, re-run repros, honest final report.

### 5. Publish (same as the 2D skill)

Screenshot via `?shot=1` autopilot (headless Chrome, 900×680) → `shots/<game>.png`;
`entry.json` `{ "title", "company", "year", "description" }`; from
`~/Code/one-page-arcade/`:
`./publish-to-blog.sh <game>.html <game>-parts/entry.json <game>-parts/shots/<game>.png`
→ live at `https://choukalos.com/arcade/<game>.html` within ~30s. Add a style-matched
README section (note "requires WebGL — Three.js r160 inlined, ~700KB, still
self-contained").

## WebGL crash patterns (from `skiing-gl-crash-investigation.md`)

**Safari black screen after ~50s of play** — root cause proven, not speculation:
Safari's WebKit/ANGLE **GPU process wedges or dies** (silent — no crash report); the
WebGL context is lost; WebKit's auto-restore requests a new context that the wedged GPU
process can never create; the JS context object is invalidated so any GL call throws
("shaderSource must be an instance of WebGLShader" — symptom, not cause); Three.js r160
`render()` silently returns while `contextLost`, so the canvas stays black forever.
**Reloading the page does not help** — the wedged GPU process lives for the whole Safari
instance; only Cmd+Q (or a reboot) fixes it. Consequences:

1. The hardening in **04-js-setup.js** is mandatory for every WebGL game — the
   per-frame `isContextLost()` poll catches the wedge even when the
   `webglcontextlost` event is missed, and the GRAPHICS CRASHED overlay tells the user
   the real fix (reload → quit Safari → reboot + updates).
2. Never pre-create the WebGL context on the canvas — it breaks Three.js's own
   webgl2→webgl1 fallback (a forced-WebGL1 hack cannot help: Safari's WebGL1 and WebGL2
   both run on ANGLE in the same GPU process).
3. When diagnosing "it works in Chrome, black in Safari": first suspect the GPU process,
   not the game code — verify with headless Chrome (real GPU) + the node tests before
   touching game logic, and check `/Library/Logs/DiagnosticReports/` for
   `com.apple.WebKit.GPU` wedges in the user's test window.

## Verification

- Syntax check passes on every `<script>` block; smoke + bot (+ crash-overlay for WebGL)
  all green — report the counts.
- Headless-Chrome screenshot shows real 3D rendering (not a black canvas) — title and a
  mid-gameplay frame.
- Report final size — WebGL games run ~700KB (Three.js dominates); pseudo-3D canvas games
  run 15–35KB.
- If published: `curl -sI https://choukalos.com/arcade/<game>.html` → 200.
