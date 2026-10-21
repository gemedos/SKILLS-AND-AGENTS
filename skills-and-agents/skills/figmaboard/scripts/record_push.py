#!/usr/bin/env python3
"""Record a push result in figmaboard.json and prepare image uploads.

Save the JSON that use_figma returned to a file, then:
  python3 record_push.py --state DIR --result push_1.result.json [--file-url URL] [--assets DIR]

It stores Figma node ids + hashes per artboard (this is what makes the next sync cost one call),
promotes the rendered spec to the sync baseline, fills __PAGE__/__SECTION__ in any remaining
push_N.js scripts, and writes out/uploads.json when raster images still need uploading.
"""
import argparse
import base64
import datetime
import json
import mimetypes
import os
import re
import sys
import urllib.parse

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import fbcommon as fb  # noqa: E402


def dfs(n, acc):
    acc.append(n)
    for k in n.get("k", []) or []:
        dfs(k, acc)
    return acc


def resolve_src(src, man, ab_key, assets):
    root = man["board"]["root"]
    if src.startswith("data:"):
        m = re.match(r"data:([^;,]+)?(;base64)?,(.*)", src, re.S)
        if not m:
            return None, None
        ext = mimetypes.guess_extension(m.group(1) or "image/png") or ".png"
        data = base64.b64decode(m.group(3)) if m.group(2) else urllib.parse.unquote_to_bytes(m.group(3))
        path = os.path.join(man["_state"], "out", "img_%d%s" % (abs(hash(src)) % 10 ** 8, ext))
        with open(path, "wb") as f:
            f.write(data)
        return path, m.group(1) or "image/png"
    if src.startswith("/_blob/"):
        bid = src.split("/_blob/")[1].split("?")[0]
        if assets and os.path.isdir(assets):
            for fn in os.listdir(assets):
                if os.path.splitext(fn)[0] == bid:
                    p = os.path.join(assets, fn)
                    return p, mimetypes.guess_type(p)[0] or "image/png"
        return None, None
    if re.match(r"https?://", src):
        return src, mimetypes.guess_type(src.split("?")[0])[0] or "image/png"
    if src.startswith("file://"):
        src = src[7:]
    base = os.path.join(root, os.path.dirname(ab_key))
    p = os.path.normpath(os.path.join(base, urllib.parse.unquote(src)))
    if os.path.exists(p):
        return p, mimetypes.guess_type(p)[0] or "image/png"
    return None, None


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--state", required=True)
    ap.add_argument("--result", required=True, nargs="+")
    ap.add_argument("--file-url")
    ap.add_argument("--plan-key", help="team::N / organization::N used for create_new_file (remembered for next time)")
    ap.add_argument("--assets")
    a = ap.parse_args()

    mp = os.path.join(a.state, fb.MANIFEST_NAME)
    man = fb.load_json(mp)
    pending = fb.load_json(os.path.join(a.state, fb.SPEC_NAME + ".pending"))
    base = fb.load_json(os.path.join(a.state, fb.SPEC_NAME)) or {"v": 1, "artboards": []}
    by_key = {ab["key"]: ab for ab in pending["artboards"]}
    base_keys = {ab["key"]: i for i, ab in enumerate(base["artboards"])}

    summary = {"recorded": [], "conflicts": [], "errors": [], "fonts": {}}
    images = []
    for rp in a.result:
        res = fb.load_json(rp)
        if isinstance(res, list):  # some clients wrap the return value
            res = res[0]
        if "result" in res and isinstance(res["result"], dict):
            res = res["result"]
        man["figma"]["pageId"] = res.get("page") or man["figma"].get("pageId")
        man["figma"]["sectionId"] = res.get("section") or man["figma"].get("sectionId")
        if res.get("fileKey"):
            man["figma"]["fileKey"] = res["fileKey"]
        summary["conflicts"] += res.get("conflicts", [])
        summary["errors"] += res.get("err", [])
        summary["fonts"].update(res.get("fonts", {}))
        man["fontMap"].update(res.get("fonts", {}))
        for key, r in (res.get("abs") or {}).items():
            spec_ab = by_key[key]
            nodes = dfs(spec_ab["node"], [])
            if len(nodes) != len(r["ids"]):
                summary["errors"].append(f"{key}: node count mismatch {len(nodes)} vs {len(r['ids'])}")
            nmap, hs = {}, {}
            for n, nid, h in zip(nodes, r["ids"], r["hs"]):
                nmap[nid] = n.get("i")
                if h:
                    hs[nid] = h
            man["artboards"][key] = {"frameId": r["id"], "fh": r["fh"], "nodes": nmap, "hs": hs,
                                     "boardHash": None}
            if key in base_keys:
                base["artboards"][base_keys[key]] = spec_ab
            else:
                base_keys[key] = len(base["artboards"])
                base["artboards"].append(spec_ab)
            summary["recorded"].append(key)
            for nid, src in res.get("img", []) or []:
                if nid in nmap or nid == r["id"]:
                    images.append((nid, src, key))
    # board file hashes, to detect board edits since this sync
    root = man["board"]["root"]
    for key in summary["recorded"]:
        f = os.path.join(root, "project", key) if man["board"]["kind"] == "design" else os.path.join(root, key)
        if os.path.exists(f):
            man["artboards"][key]["boardHash"] = fb.file_hash(f)
    base["tokens"] = pending["tokens"]
    base["origins"] = pending.get("origins", {})
    base["board"] = pending["board"]
    man["tokens"] = pending["tokens"]
    if a.file_url:
        man["figma"]["fileUrl"] = a.file_url
    if a.plan_key:
        man["figma"]["planKey"] = a.plan_key
    man["lastSync"] = {"at": datetime.datetime.now(datetime.timezone.utc).isoformat(timespec="seconds"), "dir": "board->figma"}
    fb.save_json(os.path.join(a.state, fb.SPEC_NAME), base, compact=True)
    fb.save_json(mp, man)

    # fill placeholders in remaining push scripts
    outdir = os.path.join(a.state, "out")
    rest = []
    for fn in sorted(os.listdir(outdir)) if os.path.isdir(outdir) else []:
        if re.match(r"push_\d+\.js$", fn):
            p = os.path.join(outdir, fn)
            s = fb.read_text(p)
            if "__PAGE__" in s or "__SECTION__" in s:
                s = s.replace("__PAGE__", man["figma"]["pageId"] or "").replace("__SECTION__", man["figma"]["sectionId"] or "")
                fb.write_text(p, s)
                rest.append(p)
    summary["nextScripts"] = rest

    # image uploads
    man["_state"] = a.state
    ups, missing = [], []
    for nid, src, key in images:
        path, ctype = resolve_src(src, man, key, a.assets)
        if path:
            ups.append({"nodeId": nid, "src": src, "path": path, "contentType": ctype})
        else:
            missing.append(src)
    del man["_state"]
    for nid, src, key in images:
        man.setdefault("pendingImages", {})[nid] = "FILL"
    # merge with uploads still waiting from an earlier chunk of the same push (one upload call in total)
    prev = fb.load_json(os.path.join(outdir, "uploads.json"))
    if prev and prev.get("files"):
        have = {u["nodeId"] for u in ups}
        ups = [u for u in prev["files"] if u["nodeId"] not in have] + ups
    if ups:
        plan = {"fileKey": man["figma"]["fileKey"], "count": len(ups[:60]), "nodeIds": [u["nodeId"] for u in ups[:60]],
                "pageId": man["figma"]["pageId"], "files": ups[:60]}
        fb.save_json(os.path.join(outdir, "uploads.json"), plan)
        summary["uploads"] = {"plan": os.path.join(outdir, "uploads.json"), "count": len(ups[:60]),
                              "call": {"tool": "upload_assets", "fileKey": plan["fileKey"], "count": plan["count"],
                                       "nodeIds": plan["nodeIds"], "currentPageId": plan["pageId"]}}
        if len(ups) > 60:
            summary["uploads"]["note"] = f"{len(ups)} images: only the first 60 fit in one upload_assets call"
    if missing:
        summary["imagesMissing"] = missing
    print(json.dumps(summary, indent=1))


if __name__ == "__main__":
    main()
