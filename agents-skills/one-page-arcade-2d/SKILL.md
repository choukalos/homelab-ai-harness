---
name: one-page-arcade-2d
description: Build classic 2D arcade games as a single self-contained HTML file (canvas + inline CSS + vanilla JS + procedural WebAudio, no dependencies) via the design → plan → parts → assemble → headless-QA workflow, then publish to the homelab blog /arcade. Use when the user wants a 2D arcade game — shooter, platformer, puzzle, beat-em-up — rebuilt or new, or to fix/QA an existing one-page 2D game.
---

# One-Page Arcade 2D — single-file HTML arcade games

Each game is **one self-contained `.html` file** — HTML5 canvas rendering, inline CSS
(CRT scanlines/vignette, HUD, overlay dialogs), vanilla JS (no frameworks), procedural
WebAudio (oscillators + noise buffers, no audio files), `localStorage` hi-score. No
dependencies, no build tools, no external assets — open the file and play. Reference
library (Mac): `~/Code/one-page-arcade/` — `ARCHITECTURE.md` (the full developer guide),
built games (pac-man, asteroids, tetris, moon-patrol, galaga, depth-charge,
missile-command, lunar-lander, joust, pitfall, kungfu, double-dragon, rolling-thunder,
star-trek), per-game `*-plan.md` / `*-build-plan.md` / `*-qa-plan.md`, and `*-parts/`
dirs (part files + `tests/` + `shots/` + `entry.json`).

## When to use

- Rebuild a classic 2D arcade game (Pac-Man, Moon Patrol, Tetris, Pitfall!, …).
- A new 2D arcade-style game as a single HTML file.
- Fix / QA an existing one-page 2D game (jump to **QA**).

For 3D/WebGL games (or the pseudo-3D perspective-on-canvas pattern) use the
`one-page-arcade-3d` skill instead.

## Workflow — design → plan → parts → assemble → QA → publish

### 1. Design (`<game>-design.md`)

- Goal, genre, **scope in/out** (1 player only by default — 2-player keyboard layouts are
  out of scope), mechanics list.
- **Key design numbers — exact values the builder must use:** physics constants
  (accel/friction/gravity), speeds, spawn rates, entity caps, scoring, lives, extra-life
  thresholds, wave escalation, state machine (`TITLE → READY → PLAYING → (DYING |
  LEVEL_CLEAR) → GAMEOVER`, `PAUSED`), palette (hex), audio list (the `playSound` cases),
  controls.
- If rebuilding from a gameplay video: extract frames first (`video-analyze` skill) and
  produce an analysis doc (HUD layout, sprite geometry, timing tables, key design
  decisions) — the depthcharge / rollingthunder analysis pattern.

### 2. Build plan (`<game>-build-plan.md`)

- **Part-file table (assembly order):** `01-head.html` (CSS) · `02-body.html` (HUD,
  canvas, overlay) · `03-js-core.js` (canvas/resize, audio, constants, helpers, starfield,
  state) · `04…0N` game-specific (terrain, player, combat, sprites) · last part = flow
  (`initGame`/`update`/`draw`/`loop`) + closing tags.
- Assembly command (`cat` parts → `game.html`) + the syntax-check command.
- **Turn discipline:** one part file per write call, ≤ ~6–7KB each; no reading whole game
  files (grep with `head` only); assemble + syntax-check at the end, then integrate in
  small edits.
- Test plan: smoke / bot / diag (below), plus data-integrity checks for level data.

### 3. Parts — architecture conventions (ARCHITECTURE.md)

- **Sizing:** `canvas.width = min(innerWidth-100, 900)`, `height = min(innerHeight-20,
  680)`, floors 500×420; `resize()` on window resize.
- **HTML skeleton:** `#crt` (scanline + vignette overlay, `pointer-events:none`), `#hud`
  (score/hi/level spans), `canvas#c`, `#overlay/#msgBox` (start/game-over/pause dialog)
  with color classes (`.c-yellow/.c-green/.c-red/.c-cyan/.c-amber/.c-white`).
- **Audio:** `ensureAudio()` lazily creates the `AudioContext`; `playSound(type)` switch
  of oscillator / noise-buffer SFX. No audio files.
- **Helpers:** `R(a,b)` random, `dist`, `L` (lerp), `C` (clamp), `PI2`.
- **Background:** starfield `initStars()`/`tickStars()` — **call `initStars()` before
  `loop()` starts so `draw()` never sees undefined state.**
- **State:** initialize ALL state variables before the first frame; `draw()` guards
  `!gameStarted || gameOver` (draw the title screen on the canvas, then early-return).
- **Juice:** screen shake (`shakeT`/`shakeI` — translate in `draw()`, decrement after),
  particle explosions (spawn → fade with `globalAlpha`), score popups.
- **Hi-score:** `localStorage` key `<game>_hi`, saved on game over.
- **UI:** `showMsg(html)` / `hideMsg()` for the overlay dialog.
- **Controls:** keyboard primary — arrows/WASD for movement, game keys for actions,
  `P` pause, `Space`/`Enter` start/retry; mouse aim where the game calls for it; optional
  touch (`touchstart` with `preventDefault` → the same action handler — depth-charge
  pattern).
- **`?shot=1` shot mode:** a URL param that enables an autopilot (`shotPilot()`) which
  plays the game unattended — used for headless screenshots and bot tests.

### 4. Assemble

```sh
cd <game>-parts
cat 01-head.html 02-body.html 03-js-core.js … 0N-js-flow.js > ../<game>.html
node -e "
const fs = require('fs');
const html = fs.readFileSync('<game>.html', 'utf8');
const m = html.match(/<script>([\s\S]*?)<\/script>/);
if (m) { try { new Function(m[1]); console.log('JS: OK'); } catch(e) { console.log('ERROR:', e.message); } }
console.log('File:', html.length, 'bytes,', html.split('\n').length, 'lines');
"
```

### 5. QA (headless, node)

The harness extracts the `<script>` from the assembled HTML and runs it in Node with
stubbed browser globals (Proxy no-op canvas ctx, fake `document`/`window`/
`localStorage`, `requestAnimationFrame` captured into a driver that steps frames; the
game's own `?shot=1` autopilot or scripted key presses drive it). See
`moon-patrol-parts/tests/` and `pac-man-parts/tests/` for the pattern.

- **smoke-test.js** — state transitions (TITLE→READY→PLAYING→GAMEOVER, pause, restart),
  core mechanics (movement/turns, collisions, scoring, respawn, level clear), bounds
  (no NaN, all positions in range).
- **bot-test.js** — autopilot plays many frames / multiple levels / lives; assert no NaN,
  entity caps hold, no crash, score finite.
- **diag-test.js** — level-data integrity. For mazes: BFS connectivity from every open
  tile (a single misplaced wall breaks the game — the #1 failure mode), exact dot/pellet
  counts, symmetry.
- **QA plan for a reported bug** (moon-patrol-qa-plan pattern): investigate in parallel
  read-only lanes — `visual-render` (canvas state leaks: shadowBlur/globalAlpha/
  transforms; z-order; HUD) · `gameplay-physics` · `flow-logic` (state machine, waves,
  scoring, respawn) · `runtime-robustness` (long stress, resize, spam inputs, restart
  while paused, unbounded arrays, setTimeout leaks). Each finding: `ID | severity
  (blocker/major/minor) | file:line | symptom | repro | root cause | suggested fix`.
  Fix **sequentially in the part files** (one writer — no git worktree), reassemble,
  re-run each repro; final gate = full verification + an honest report of what was fixed
  and what still needs a human browser playtest.
- "No exceptions" is not QA — verify behavior against the design doc, not just that it
  runs.

### 6. Publish (optional)

1. Screenshot: `?shot=1` autopilot → headless Chrome screenshot at 900×680 →
   `<game>-parts/shots/<game>.png`.
2. `entry.json` in the parts dir: `{ "title", "company", "year", "description" }`.
3. From `~/Code/one-page-arcade/`:
   `./publish-to-blog.sh <game>.html <game>-parts/entry.json <game>-parts/shots/<game>.png`
   — copies the game + shot into `~/Code/homelab-blog/static/arcade/`, merges the entry
   into `data/arcade/games.json`, commits + pushes blog `main`, runs the blog's
   `deploy.sh`. Live at `https://choukalos.com/arcade/<game>.html` within ~30s.
4. Add a style-matched section to `~/Code/one-page-arcade/README.md` (genre line,
   feature bullets, **Controls** line).

## Verification

- Syntax check passes; smoke + bot + diag all green (report the counts).
- Screenshot (or vision-inspected frames) shows the game rendering — title screen and a
  mid-gameplay frame.
- Report final size (bytes/lines) — 2D games run 10–35KB.
- If published: `curl -sI https://choukalos.com/arcade/<game>.html` → 200.

## Known pitfalls

- Uninitialized state before the first frame → `draw()` crashes on undefined (see the
  starfield rule).
- Canvas state leaks — `shadowBlur`, `globalAlpha`, `ctx.translate` persist across frames;
  reset them after use (screen-shake translates must be undone).
- Maze/level data: verify connectivity + counts **before** building the rest of the game.
- Physics drift: assert `isFinite` on positions in the bot test; NaN usually means a
  divide-by-zero or an unclamped input.
