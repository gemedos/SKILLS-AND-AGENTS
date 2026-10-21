#!/usr/bin/env python3
"""Build the use_figma script(s) that push a rendered board into Figma.

Run render_board.py first. Normally this prints ONE script: everything (tokens, text styles,
all artboards, the readback hashes and a screenshot) happens in a single use_figma call.
A second script is only emitted when the code would exceed the use_figma 50,000-character limit.

Usage:
  python3 build_push.py --state DIR --file-key KEY [--page-id ID | --new-page NAME | --rename-first NAME]
                        [--only KEY,KEY] [--force KEY,KEY|all] [--no-shot] [--max 48500]

  --new-page      add a new page to an existing Figma file (first sync into a file the user gave)
  --rename-first  use and rename the first page (first sync into a brand-new file)
  (re-syncs read the page and section from figmaboard.json; no page flag needed)
  --force         rebuild these artboards even if they were edited in Figma since the last sync

Writes <state>/out/push_1.js (and push_2.js ... if needed) and prints a JSON plan.
"""
import argparse
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import fbcommon as fb  # noqa: E402

HERE = os.path.dirname(os.path.abspath(__file__))
DROP = {"i", "tp", "tprop", "sprops", "loose"}


def slim(n):
    o = {k: v for k, v in n.items() if k not in DROP and k != "k"}
    if o.get("t") == "T":
        o.pop("n", None)  # Figma names text layers after their content
    if n.get("k"):
        o["k"] = [slim(c) for c in n["k"]]
    return o


def minify(js):
    return fb._strip_js(js)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--state", required=True)
    ap.add_argument("--file-key")
    ap.add_argument("--page-id")
    ap.add_argument("--new-page")
    ap.add_argument("--rename-first")
    ap.add_argument("--only")
    ap.add_argument("--force", default="")
    ap.add_argument("--no-shot", action="store_true")
    ap.add_argument("--max", type=int, default=48500)
    a = ap.parse_args()

    man = fb.load_json(os.path.join(a.state, fb.MANIFEST_NAME))
    spec = fb.load_json(os.path.join(a.state, fb.SPEC_NAME + ".pending"))
    if not man or not spec:
        sys.exit("run render_board.py first (no manifest or pending spec in %s)" % a.state)
    file_key = a.file_key or man["figma"].get("fileKey")
    if not file_key:
        sys.exit("no Figma file yet: pass --file-key (from create_new_file or the user's Figma URL)")
    if man["figma"].get("fileKey") and man["figma"]["fileKey"] != file_key:
        # new target file: forget old node ids
        man["artboards"] = {}
        man["figma"].update({"pageId": None, "sectionId": None})
    runtime = fb.runtime_code()
    only = set(a.only.split(",")) if a.only else None
    force_all = a.force == "all"
    force = set(a.force.split(",")) if a.force and not force_all else set()

    page = {}
    if man["figma"].get("pageId") and not a.new_page:
        page = {"id": man["figma"]["pageId"]}
    elif a.page_id:
        page = {"id": a.page_id}
    elif a.new_page:
        page = {"create": a.new_page}
    elif a.rename_first:
        page = {"rename": a.rename_first}

    jobs = []
    for ab in spec["artboards"]:
        if only and ab["key"] not in only:
            continue
        prev = man["artboards"].get(ab["key"], {})
        job = {"key": ab["key"], "x": ab["x"], "y": ab["y"], "node": slim(ab["node"])}
        if prev.get("frameId"):
            job["replace"] = prev["frameId"]
            job["expect"] = prev.get("fh")
            if force_all or ab["key"] in force:
                job["force"] = 1
        jobs.append(job)

    base = {"mode": "push", "title": spec["board"]["title"],
            "coll": man["figma"].get("collection") or (spec["board"]["title"] + " tokens"),
            "page": page, "section": {"id": man["figma"].get("sectionId")}, "tokens": spec["tokens"],
            "imgs": man.get("images", {}), "pending": man.get("pendingImages", {}), "shot": not a.no_shot, "abs": []}

    def code_for(abs_):
        p = dict(base, abs=abs_)
        return "const P = " + json.dumps(p, ensure_ascii=False, separators=(",", ":")) + ";\n" + runtime

    chunks, cur = [], []
    for j in jobs:
        trial = cur + [j]
        if len(code_for(trial)) > a.max and cur:
            chunks.append(cur)
            cur = [j]
        else:
            cur = trial
    if cur:
        chunks.append(cur)

    outdir = os.path.join(a.state, "out")
    os.makedirs(outdir, exist_ok=True)
    plan = {"fileKey": file_key, "calls": []}
    for i, ch in enumerate(chunks, 1):
        code = code_for(ch)
        if i > 1:
            # later chunks reuse the page/section created by chunk 1 -> patched by record_push.py
            code = code.replace('"page":' + json.dumps(page, separators=(",", ":")), '"page":{"id":"__PAGE__"}', 1)
            code = code.replace('"section":{"id":' + json.dumps(man["figma"].get("sectionId")) + "}", '"section":{"id":"__SECTION__"}', 1)
        path = os.path.join(outdir, f"push_{i}.js")
        fb.write_text(path, code)
        too_big = len(code) > 50000
        plan["calls"].append({"file": path, "chars": len(code), "artboards": [j["key"] for j in ch],
                              "tooBig": too_big})
    man["figma"]["fileKey"] = file_key
    fb.save_json(os.path.join(a.state, fb.MANIFEST_NAME), man)
    plan["note"] = ("Send push_1.js with use_figma. " +
                    ("Then run record_push.py, which fills __PAGE__/__SECTION__ in the next scripts; send them in ONE message (parallel)."
                     if len(chunks) > 1 else "One call."))
    if any(c["tooBig"] for c in plan["calls"]):
        plan["warning"] = "An artboard alone exceeds 50,000 characters. Split it into several artboards on the board, or push it with --only after simplifying."
    print(json.dumps(plan, indent=1))


if __name__ == "__main__":
    main()
