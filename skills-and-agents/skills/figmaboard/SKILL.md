---
name: figmaboard
description: Turns a design board (a Claude Design canvas or local HTML/CSS mockups) into an editable Figma file with auto layout, color/spacing variables and text styles, and syncs edits back the other way (Figma -> board), or creates an HTML board from existing Figma frames. Built to spend as few Figma MCP calls as possible (normally one use_figma call per sync). Use whenever the user says /figmaboard, wants to send, push, export or open a board, mockup, canvas or HTML page in Figma, wants to pull, sync or bring Figma changes back into the board, or wants to turn Figma frames into HTML. Spanish triggers too: "pasa este tablero a Figma", "lleva el diseño a Figma", "sincroniza con Figma", "trae los cambios de Figma", "convierte este Figma en HTML".
---

# figmaboard

Moves a design board into Figma so it can be edited freely there, then brings the edits back,
and the reverse. Heavy work (rendering, layout analysis, diffing, patching) runs in local Python
scripts. Figma only gets **one generated `use_figma` script per sync**: it builds or reads,
checks for conflicts and returns hashes (plus a screenshot for pushes) in that one call.

Paths below are relative to this skill's folder (`scripts/...`).

## Call budget (the promise to the user)

| Run | Figma MCP calls |
|---|---|
| Board -> Figma, file URL given or board already linked | **1** `use_figma` |
| Board -> Figma, brand-new file | `create_new_file` + 1 (+ `whoami` once, only if the plan key is unknown) |
| Figma -> board (linked board) | **1** `use_figma` (returns only what changed) |
| Figma -> new HTML board | **1** `use_figma` |
| Extra, only when needed | +1 `upload_assets` if the board has raster images not yet in Figma; +1 `download_assets` if Figma has new images the board lacks |

Rules that keep it there:

- **Never** call `get_metadata`, `get_design_context`, `get_variable_defs` or `get_screenshot` in this
  skill. They are rate-limited reads (View/Collab seats: ~20 per month). The generated `use_figma`
  scripts do all the reading and return a screenshot inline.
- Send each generated `.js` file **verbatim** as the `code` argument (read the file, paste all of it).
  Never rewrite or "improve" it. Pass `skillNames: "figmaboard"`.
- The scripts already follow Figma's figma-use rules, so don't spend a call loading `figma-use` for
  them. If the Figma plugin is installed locally, loading `/figma-use` is free, so load it then. If
  you ever have to hand-write or repair Plugin API code, load figma-use first.
- Save every tool result to a JSON file right away (Write tool). The next script reads it.
- After an error, retry the same script **once** only if the error says
  `safeToRetryWithoutCanvasRead: true`. Otherwise stop and report.
- If a result contains `more`, rerun the same build step with `--start <more>`. That is the only
  case where a sync takes a second read call.

## Requirements (check once per session)

- Figma MCP server connected, remote server (`https://mcp.figma.com/mcp`). Writing outside drafts
  needs a Full seat. Writing into the user's drafts works on any seat.
- `python3` with `playwright` and Chromium (`pip install playwright && python -m playwright install chromium`).
  Check with `python3 -c "import playwright"`. If Chromium is preinstalled elsewhere, the scripts find it.
- Image uploads POST to `mcp.figma.com`. If that host is blocked by network policy, images stay as
  grey placeholder layers and everything else still works. Tell the user once.

## Step 0: work out the flow

| The user has | The user wants | Flow |
|---|---|---|
| a board, no `figmaboard.json` yet | it in Figma | **A** (first push) |
| a linked board (`figmaboard.json` exists) | board edits in Figma | **A** (re-push) |
| a linked board | Figma edits in the board | **B** (pull) |
| a Figma URL only | a board to edit | **C** (Figma-first) |

The board is either:
- a **Claude Design canvas** (claude.ai artifact link, or a folder with `project/canvas.json`).
  Bring it into a local folder first, as described in `references/design-canvas.md`. All script
  paths then point at that folder.
- **local HTML**: one `.html` file or a folder of them. Work on it in place.

The state lives next to the board: `figmaboard.json` (links, hashes) and `figmaboard.spec.json`
(last synced layout). For canvases that is `project/_figmaboard/`. Below, `STATE` means that folder.

If the direction is unclear ("sync it"), ask one question: push board to Figma, or pull Figma into
the board? If the user is not there to answer, pull first (it never overwrites Figma) and say so.

## Flow A: board -> Figma

1. Render and measure the board (local, no Figma call):
   `python3 scripts/render_board.py --board <board> [--assets <dir>]`
   It adds `data-fb="nN"` ids to element tags in the source files (harmless attributes that let
   later syncs find each element) and prints `sourcesChanged`. Canvases: `--assets` is the folder of
   downloaded `/_blob/` images.
2. Pick the target file:
   - board already linked: nothing to do.
   - user gave a Figma file URL: take the `fileKey` from it (`figma.com/design/<fileKey>/...`) and
     add `--new-page "<board title>"` in step 3 so their existing pages are untouched.
   - otherwise create a file. Plan key: reuse one you already know (an earlier `figmaboard.json`
     `figma.planKey`, or the conversation). Otherwise call `whoami`: one plan means use its `key`,
     several means ask which. Then call `create_new_file` (fileName = board title,
     editorType `design`) and add `--rename-first "<board title>"` in step 3.
3. Build the script:
   `python3 scripts/build_push.py --state STATE --file-key <key> [--new-page T | --rename-first T]`
   It prints the plan. Normally `push_1.js` is one call. A board too big for one call is split
   across `push_2.js`... (rare).
4. Send `STATE/out/push_1.js` with `use_figma`. Save the JSON result to `STATE/out/push_1.result.json`.
   The result also shows a screenshot of the new Figma section. Glance at it to sanity-check.
5. Record it: `python3 scripts/record_push.py --state STATE --result STATE/out/push_1.result.json --file-url <url> [--plan-key <key>]`
   - `conflicts` not empty: those artboards were edited in Figma since the last sync and were **not**
     overwritten. Ask the user: pull those edits into the board first (Flow B, then push again), or
     overwrite Figma (`build_push.py ... --force <keys>`).
   - `nextScripts`: send them all in **one message** (parallel), then record each result.
   - `uploads` (after the last script is recorded, since chunks share one upload plan): make the
     single `upload_assets` call exactly as printed (`fileKey`, `count`,
     `nodeIds`, `currentPageId`). Save its result, then run
     `python3 scripts/upload_images.py --state STATE --response <result.json>`. If it reports
     `blocked`, tell the user the images are placeholders and why.
6. Canvas boards: publish the changed sources and the state files back to the canvas, as described
   in `references/design-canvas.md`. HTML boards are already updated on disk.
7. Tell the user: the Figma link, what was created (pages, frames, variables, text styles), any font
   substitutions from `fonts` (for example "system-ui -> Inter"), and the calls used.

## Flow B: Figma -> board

1. Canvas boards: refresh the local copy first (`references/design-canvas.md`), so edits made in the
   canvas since the last sync are included.
2. `python3 scripts/build_pull.py --state STATE`, then send `STATE/out/pull.js` with `use_figma`. Save
   the result to `STATE/out/pull.result.json`.
   - Every artboard `same`: tell the user nothing changed in Figma and stop. That was 1 call.
3. Apply: `python3 scripts/apply_pull.py --state STATE --result STATE/out/pull.result.json [--images <dir>]`
   It patches only the changed elements (inline styles, text, added/removed elements, token values),
   writes Design-canvas props (`data-props` defaults) when a value came from one, re-renders the
   board locally and records the new hashes.
4. Read the report:
   - `needsDecision`: show each item and ask what to do. Typical cases: an artboard deleted in
     Figma, an element generated by a `<sc-for>` loop (edit its data in `renderVals()` instead), or
     a board that also changed since the last sync.
   - `imagesNeeded`: new images in Figma. If the user wants them, make **one** `download_assets`
     call for those node ids, save the files as `<imageHash>.<ext>` in a folder, and rerun
     `apply_pull.py ... --images <folder>`.
   - `newArtboards`: frames added in Figma became new board files.
5. Canvas boards: publish `filesChanged` (and any new artboards plus `canvas.json`) back to the canvas.
6. Summarize for the user in plain words: what changed and where, and what still needs a decision.

## Flow C: Figma -> new HTML board

1. From the URL take `fileKey` and, if present, `node-id` (`12-34` -> `12:34`). The node can be a
   frame, a section or a page. Without a node id, the first page's top-level frames are read.
2. `python3 scripts/build_pull.py --dump --file-key <key> [--target <node-id>] --out <new folder>`.
   Send `<new folder>/_figmaboard_out/dump.js` with `use_figma`. Save the result next to it.
3. `python3 scripts/apply_pull.py --dump --out <new folder> --file-key <key> --result <result.json> [--single]`
   Use `--single` when the target was a single frame, so other frames on the page aren't treated
   as new. You get one `.html` per frame, `tokens.css` (Figma color variables as CSS variables) and
   `figmaboard.json`. From then on the folder is a linked board, so Flows A and B apply.
4. If `imagesNeeded` lists images, offer the one `download_assets` call and rerun with `--images`.
5. Write the folder where the user wants it (a connected folder, or deliver the files), and say how
   many frames, tokens and images came across.

## What maps to what

- Flex and grid containers become auto layout (gap, padding, alignment, wrap). Block stacks with
  even spacing become vertical auto layout. Anything else keeps absolute positions.
- Colors become variables (`color/<name>`): names come from CSS custom properties or Design-canvas
  color props when they exist, otherwise from the color's role (`bg-1`, `text-2`, `border-1`).
  Repeated gaps, paddings and radii become `space/N` and `radius/N`.
- Text keeps family, weight, size, line height, letter spacing, alignment, case, decoration and
  inline runs (bold spans, colored words, links). Each distinct combination becomes a text style.
- Inline SVG becomes editable vectors. `<img>` and CSS background images become image fills.
- Not carried over (say so if it matters): hover/interaction states, scripts and template logic
  (Figma gets the rendered result), transforms and rotation, CSS filters, radial gradients, video,
  and custom uploaded fonts (Figma falls back to the closest available family). Pushing rebuilds
  the synced frames, so Figma-only extras on them (components, prototype links, comments pinned to
  layers) don't survive a push. Pull first if the Figma side matters.

Details for debugging and edge cases: `references/troubleshooting.md`. The spec format is in
`references/spec-format.md`.
