# Working with a Claude Design canvas

A Design canvas is a claude.ai artifact whose files live under `project/`:
`project/canvas.json` (the index: artboards, positions, sizes) and one `project/<Name>.dc.html` per
artboard. figmaboard works on a local copy of those files and publishes the changed ones back.
None of this uses Figma calls.

## Contents
- Fetch the canvas into a local folder
- Images on the canvas
- Publish changes back
- How the canvas format is handled

## Fetch the canvas into a local folder

1. `Artifact` `action: "read"`, `url: <canvas link>`, `path: "project/canvas.json"`. The result says
   where the file was saved: `<folder>/project/canvas.json`. That `<folder>` is the **board root**
   from here on. Read the JSON and collect every `boards` key (artboard paths).
2. One `Artifact` read with `paths`: every `project/<key>` from `boards`, plus
   `project/_figmaboard/figmaboard.json` and `project/_figmaboard/figmaboard.spec.json`. On a first
   sync the two state files don't exist, which is expected. Files a `<dc-import>` pulls in are
   artboards too, so they're already in `boards`.
3. The board for the scripts is `<folder>` (the folder that contains `project/`), and
   `STATE` = `<folder>/project/_figmaboard`.

Re-fetch before every Flow B run and before a re-push, because people may have edited the canvas
in the browser since the last sync.

## Images on the canvas

Artboards reference uploads as `/_blob/<id>`. For each distinct id in the artboard files:
`Artifact` read with `url` and `path: "<id>"` (the 32-hex asset id). Copy every saved file into
`<folder>/_assets/<id>.<ext>`, then pass `--assets <folder>/_assets` to `render_board.py` and
`record_push.py`. Skip this when the board has no `/_blob/` references.

## Publish changes back

After `render_board.py` (when `sourcesChanged` is not empty) or `apply_pull.py` (when
`filesChanged` / `newArtboards` is not empty), publish in **one** `Artifact` call:

```
action: publish
url: <canvas link>
root: <folder>
file_path: <folder>/project/<first changed artboard>
files: {
  "project/<other changed artboard>": "project/<other changed artboard>",
  "project/_figmaboard/figmaboard.json": "project/_figmaboard/figmaboard.json",
  "project/_figmaboard/figmaboard.spec.json": "project/_figmaboard/figmaboard.spec.json",
  "project/canvas.json": "project/canvas.json"        <- only when artboards were added
}
```

- Never publish `*.pending`, the `out/` folder or `_assets/`.
- Always publish the two state files after a push or a pull. They are what keep the next sync to
  one call, even from another session or computer.
- If the publish is refused because someone saved the canvas meanwhile: re-fetch the files the
  refusal names and rerun the last figmaboard step on them. `apply_pull.py` patches are
  property-level, so they re-apply cleanly. After a third refusal, stop and tell the user.

## How the canvas format is handled

- `scripts/js/dc_stub.js` stands in for the canvas runtime while measuring. It fills `{{holes}}`,
  `<sc-if>`, `<sc-for>` and `<dc-import>` from `data-props` defaults and `renderVals()`, so Figma
  gets what the canvas shows by default. This render is part of the conversion the user asked for.
  It is not a design check.
- Elements repeated by `<sc-for>` get ids like `n6@0`, `n6@1`. In Figma each copy is its own layer.
  Coming back, edits to one copy can't be written to the shared template automatically, so they
  show up in `needsDecision` with the Figma values. Apply them in `renderVals()` data by hand if
  the user wants.
- A style value written as `{{prop}}` (for example `color: {{accent}}`) maps back to that prop's
  `data-props` default. A text element whose whole content is one text prop does the same.
- Color props with `"editor": "color"` become Figma variables named after the prop
  (`color/accent`). Changing that variable in Figma updates the prop default on the next pull.
- The `data-fb` attributes the scripts add are plain attributes. The canvas renders and edits
  normally with them.
