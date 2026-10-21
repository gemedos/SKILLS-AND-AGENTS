#!/usr/bin/env python3
"""POST image bytes to the URLs returned by ONE upload_assets call (no extra MCP calls).

  python3 upload_images.py --state DIR --response upload_assets.result.json

Reads out/uploads.json (written by record_push.py), posts file i to upload URL i with curl
(multipart 'file' field, raw bytes as fallback), and records image hashes in figmaboard.json
so later syncs reuse them instead of uploading again.
"""
import argparse
import json
import os
import re
import subprocess
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import fbcommon as fb  # noqa: E402


def urls_in(resp):
    found = []

    def walk(x):
        if isinstance(x, dict):
            u = next((x[k] for k in ("submitUrl", "uploadUrl", "url") if isinstance(x.get(k), str)), None)
            if u:
                found.append(x)
                return
            for v in x.values():
                walk(v)
        elif isinstance(x, list):
            for v in x:
                walk(v)
    walk(resp)
    return found


def post(url, path, ctype):
    if re.match(r"https?://", path):
        tmp = path.split("/")[-1].split("?")[0] or "image"
        tmp = os.path.join(os.path.dirname(os.path.abspath(__file__)), ".dl_" + tmp)
        subprocess.run(["curl", "-sSL", "-o", tmp, path], check=True)
        path = tmp
    r = subprocess.run(["curl", "-sS", "-w", "\n%{http_code}", "-X", "POST", "-F", f"file=@{path};type={ctype}", url],
                       capture_output=True, text=True)
    body, _, code = r.stdout.rpartition("\n")
    if not code.startswith("2"):
        r = subprocess.run(["curl", "-sS", "-w", "\n%{http_code}", "-X", "POST", "-H", f"Content-Type: {ctype}",
                            "--data-binary", f"@{path}", url], capture_output=True, text=True)
        body, _, code = r.stdout.rpartition("\n")
    return code, body


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--state", required=True)
    ap.add_argument("--response", required=True)
    a = ap.parse_args()
    plan = fb.load_json(os.path.join(a.state, "out", "uploads.json"))
    resp = fb.load_json(a.response)
    ups = urls_in(resp)
    man = fb.load_json(os.path.join(a.state, fb.MANIFEST_NAME))
    results = []
    for f, u in zip(plan["files"], ups):
        url = u.get("submitUrl") or u.get("uploadUrl") or u.get("url")
        code, body = post(url, f["path"], f["contentType"])
        h = None
        try:
            h = json.loads(body).get("imageHash")
        except Exception:
            m = re.search(r'"imageHash"\s*:\s*"([0-9a-f]+)"', body or "")
            h = m.group(1) if m else None
        if h:
            man["images"][f["src"]] = h
        if code.startswith("2"):
            man.get("pendingImages", {}).pop(f["nodeId"], None)
        results.append({"src": f["src"], "status": code, "imageHash": h})
    fb.save_json(os.path.join(a.state, fb.MANIFEST_NAME), man)
    os.replace(os.path.join(a.state, "out", "uploads.json"), os.path.join(a.state, "out", "uploads.done.json"))
    out = {"uploaded": results, "urlsReturned": len(ups), "filesPlanned": len(plan["files"])}
    if results and all(r["status"] in ("000", "403", "407") for r in results):
        out["blocked"] = ("This environment cannot reach mcp.figma.com (network/egress policy). The images stay as "
                          "placeholder layers in Figma; the sync is unaffected. Fix: allow mcp.figma.com in the "
                          "organization's network settings, or run the upload from a machine that can reach it.")
    print(json.dumps(out, indent=1))


if __name__ == "__main__":
    main()
