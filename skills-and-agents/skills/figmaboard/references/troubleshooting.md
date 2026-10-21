# Troubleshooting and limits

## Contents
- Where to run the scripts
- Errors from use_figma
- Sync looks wrong
- Size limits
- Fonts
- Images
- Rate limits and seats
- Starting over

## Where to run the scripts

The scripts need Python 3 and Playwright with Chromium. Run them where the board files are:
- Board files on the user's computer (a connected folder) and that shell has Playwright: run there.
- That shell lacks Playwright and can't install it: stage the board folder (HTML files, images and
  the two `figmaboard*.json` files) into the cloud workspace, run there, then write the changed
  files back to the same paths (pass the modification times you staged with, so you never
  overwrite newer edits).
- Design canvases are fetched into the scratchpad anyway (`design-canvas.md`).

## Errors from use_figma

| Symptom | Cause | Fix |
|---|---|---|
| `page not found` (pull) | The synced page was deleted or the file changed | Ask the user. To re-link, delete `figma.pageId`/`sectionId`/`artboards` from `figmaboard.json` and push again |
| Result has `conflicts` | Those artboards were edited in Figma after the last sync | Pull first (Flow B), or push with `--force <keys>` if the user wants Figma overwritten |
| `err` lists `svg ...` | An inline SVG Figma couldn't parse | It became an empty frame. Simplify the SVG or replace it with an `<img>` |
| `err` lists `... sizing ...` | A sizing mode wasn't valid in that spot | Harmless. The layer keeps a fixed size |
| `node count mismatch` from `record_push.py` | The page changed during the push, or the runtime was edited | Push again with `--force` for that artboard |
| Error with `safeToRetryWithoutCanvasRead: true` | Transient | Send the same script once more |
| Error with `safeToRetryWithoutCanvasRead: false` | Partial write | Don't retry blindly. Run a pull to see the state, then push with `--force` |

## Sync looks wrong

- **Everything shows as changed on a pull**: the hashes were recorded by a different runtime
  version. Push once with `--force all` to re-baseline.
- **A Figma edit didn't come back**: check `needsDecision`. Loop copies, loose text and
  template-driven text are reported there instead of patched.
- **Reordered layers in Figma**: order changes are reported as ordinary property changes. The
  element order in HTML isn't moved, except for newly added layers, which are inserted after their
  Figma predecessor.
- **Wrong layout in Figma**: flex and grid map well. Block flow with uneven margins becomes
  absolute positions on purpose, because auto layout can't express uneven gaps. Use flex with
  `gap` in the board for fully editable stacks.

## Size limits

- `use_figma` code is capped at 50,000 characters. The runtime is ~17.5 KB, which leaves ~31 KB of
  board data per call: roughly 300 to 400 layers. `build_push.py` packs as many artboards per call
  as fit. A single artboard over the cap is reported (`tooBig`). Ask the user to split it on the
  board.
- Pull and dump results are kept near 40 KB per call (`--max`). Bigger reads return `more`. Rerun
  with `--start <more>`.

## Fonts

Figma has Google Fonts but not the user's uploaded fonts. The runtime walks the CSS font stack,
maps generic families (`system-ui`, `sans-serif` -> Inter, `serif` -> Noto Serif, `monospace` ->
Roboto Mono), and picks the nearest available weight. Substitutions come back in `fonts` and are
remembered in `figmaboard.json` (`fontMap`), so they don't count as edits on later pulls.

## Images

- Board -> Figma: images are uploaded with one `upload_assets` call. Its upload URLs must be
  POSTed from a machine that can reach `mcp.figma.com`. If that's blocked (`upload_images.py`
  says `blocked`), the layers stay as grey placeholders named after the image. Hashes still match,
  so syncing isn't affected.
- Once uploaded, the image hash is remembered and later pushes reuse it without uploading again.
- Figma -> board: new or replaced images are listed in `imagesNeeded`. One `download_assets` call
  (up to 20 nodes) fetches them. It is a rate-limited read, so ask before using it on a
  View/Collab seat.

## Rate limits and seats

- Read tools (`get_*`, `download_assets`) are rate-limited. View/Collab seats get about 20 calls a
  month. figmaboard reads through `use_figma`, which Figma classes as a write tool.
- Writing to files outside the user's drafts needs a Full seat. New files from `create_new_file`
  go to drafts.
- Figma lists `use_figma` (write to canvas) as beta, free during the beta, and usage-based later.

## Starting over

Delete `figmaboard.json` and `figmaboard.spec.json` (and the `data-fb` attributes, if the user
wants clean sources) and push again. The old Figma frames stay where they were.
