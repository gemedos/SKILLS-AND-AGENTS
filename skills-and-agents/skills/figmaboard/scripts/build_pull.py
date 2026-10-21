#!/usr/bin/env python3
"""Build the use_figma script that reads Figma back.

pull (board already synced): the script receives the stored per-node hashes and returns ONLY the
nodes that changed, plus deletions, new frames and token values. Unchanged artboards cost ~10 bytes.
  python3 build_pull.py --state DIR [--max 40000]

dump (start from Figma, no board yet): returns the full layout of the frames to turn into HTML.
  python3 build_pull.py --dump --file-key KEY [--target NODE_ID] --out NEW_BOARD_DIR [--start N]

--target may be a frame, a section or a page id (from the URL's node-id, "-" -> ":").
Without --target the first page's top-level frames are read.

Writes the script to <state or out>/_figmaboard_out/pull.js (or dump.js) and prints a JSON plan.
"""
import argparse
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import fbcommon as fb  # noqa: E402

HERE = os.path.dirname(os.path.abspath(__file__))


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--state")
    ap.add_argument("--dump", action="store_true")
    ap.add_argument("--file-key")
    ap.add_argument("--target")
    ap.add_argument("--out")
    ap.add_argument("--start", type=int, default=0)
    ap.add_argument("--max", type=int, default=40000, help="soft cap on returned characters per call")
    a = ap.parse_args()
    runtime = fb.runtime_code()

    if a.dump:
        if not (a.file_key and a.out):
            sys.exit("--dump needs --file-key and --out")
        p = {"mode": "dump", "target": a.target.replace("-", ":") if a.target else None, "max": a.max, "start": a.start}
        outdir = os.path.join(a.out, "_figmaboard_out")
        os.makedirs(outdir, exist_ok=True)
        path = os.path.join(outdir, "dump.js")
        code = "const P = " + json.dumps(p, separators=(",", ":")) + ";\n" + runtime
        fb.write_text(path, code)
        print(json.dumps({"fileKey": a.file_key, "calls": [{"file": path, "chars": len(code)}],
                          "note": "One use_figma call. If the result has `more`, rerun with --start <more>."}, indent=1))
        return

    man = fb.load_json(os.path.join(a.state, fb.MANIFEST_NAME))
    if not man or not man["figma"].get("pageId"):
        sys.exit("this board has not been synced to Figma yet (no page id in figmaboard.json)")
    abs_ = {k: {"id": v["frameId"], "hs": v["hs"], "fh": v["fh"]} for k, v in man["artboards"].items() if v.get("frameId")}
    p = {"mode": "pull", "page": man["figma"]["pageId"], "section": man["figma"].get("sectionId"),
         "noNew": bool(man["figma"].get("noNew")), "coll": man["figma"].get("collection") or (man["board"]["title"] + " tokens"),
         "abs": abs_, "max": a.max, "start": a.start, "pending": man.get("pendingImages", {})}
    code = "const P = " + json.dumps(p, separators=(",", ":")) + ";\n" + runtime
    outdir = os.path.join(a.state, "out")
    os.makedirs(outdir, exist_ok=True)
    calls = []
    if len(code) <= 49500:
        path = os.path.join(outdir, "pull.js")
        fb.write_text(path, code)
        calls.append({"file": path, "chars": len(code)})
    else:
        # split artboards across scripts; send them all in ONE message (parallel)
        keys, cur, n = list(abs_), {}, 1
        for k in keys:
            trial = dict(cur, **{k: abs_[k]})
            c = "const P = " + json.dumps(dict(p, abs=trial, noNew=True), separators=(",", ":")) + ";\n" + runtime
            if len(c) > 49500 and cur:
                path = os.path.join(outdir, f"pull_{n}.js")
                fb.write_text(path, "const P = " + json.dumps(dict(p, abs=cur, noNew=n > 1), separators=(",", ":")) + ";\n" + runtime)
                calls.append({"file": path})
                n, cur = n + 1, {k: abs_[k]}
            else:
                cur = trial
        path = os.path.join(outdir, f"pull_{n}.js")
        fb.write_text(path, "const P = " + json.dumps(dict(p, abs=cur, noNew=n > 1), separators=(",", ":")) + ";\n" + runtime)
        calls.append({"file": path})
    print(json.dumps({"fileKey": man["figma"]["fileKey"], "calls": calls,
                      "note": "One use_figma call" + ("" if len(calls) == 1 else "s, sent together in one message") +
                              ". If a result has `more`, rerun with --start <more>."}, indent=1))


if __name__ == "__main__":
    main()
