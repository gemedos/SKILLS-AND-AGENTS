#!/usr/bin/env python3
"""Read-only repo scanner for the skillyfile skill.

Summarises a repository into one short Markdown report so Claude can find
repetitive work without reading every file.

Usage:
    python scan_repo.py <local-path | https://github.com/owner/repo | repo.zip>
                        [--out report.md] [--max-commits 500] [--no-api]

Guarantees:
    - Never writes inside the target repo. Clones/unzips go to a temp dir.
    - Runs only read-only git commands (log, ls-files, config --get) with
      GIT_OPTIONAL_LOCKS=0 so git does not refresh the index.
    - Never executes code from the repo.
    - Skips secret-looking files and redacts secret-looking strings.
Standard library only.
"""
import argparse
import collections
import hashlib
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import urllib.error
import urllib.request
import zipfile

# Folders that are generated or vendored: never signal, often huge.
SKIP_DIRS = {
    ".git", "node_modules", "vendor", "dist", "build", "out", ".next", ".nuxt",
    "venv", ".venv", "env", "__pycache__", "target", "coverage", ".cache",
    ".idea", ".vscode", "bin", "obj", ".terraform", ".gradle", "Pods",
}
# Files that may hold credentials: never opened.
SECRET_FILE_RE = re.compile(
    r"(^\.env(\..*)?$|\.pem$|\.key$|\.p12$|\.pfx$|^id_rsa|^id_ed25519|"
    r"credentials|secrets?\.(json|ya?ml|toml)$|\.keystore$)", re.I)
# Source/text extensions scanned for duplicates and TODOs.
CODE_EXT = {
    ".py", ".js", ".jsx", ".ts", ".tsx", ".mjs", ".cjs", ".java", ".kt", ".go",
    ".rb", ".php", ".cs", ".c", ".h", ".cpp", ".hpp", ".rs", ".swift", ".scala",
    ".sh", ".bash", ".ps1", ".sql", ".vue", ".svelte", ".dart", ".lua", ".r",
}
TEXT_EXT = CODE_EXT | {".md", ".txt", ".yml", ".yaml", ".toml", ".json",
                       ".ini", ".cfg", ".html", ".css", ".scss", ".xml"}
HIGH_SIGNAL_NAMES = re.compile(
    r"^(readme|contributing|changelog|runbook|playbook|onboarding|deploy(ment)?|"
    r"release|makefile|justfile|taskfile|dockerfile|docker-compose|"
    r"package\.json|pyproject\.toml|claude\.md|agents\.md|\.gitlab-ci|jenkinsfile|\.pre-commit-config)(\..*)?$", re.I)
HIGH_SIGNAL_DIRS = ("scripts/", "docs/", ".github/", "runbooks/", "tools/", "bin/")

MAX_FILE_BYTES = 1_000_000   # larger files are usually generated or data
MAX_FILES_SCANNED = 8000     # keeps runtime under ~1 min on big repos
DUP_WINDOW = 6               # 6 meaningful lines: below this, clones are noise
MAX_COCHANGE_FILES = 20      # bigger commits are bulk changes, not coupling

SECRET_VALUE_RE = re.compile(
    r"((api[_-]?key|token|secret|passw(or)?d|pwd|auth)\s*[:=]\s*)\S+|"
    r"\b[A-Za-z0-9_\-]{32,}\b", re.I)


def redact(text):
    return SECRET_VALUE_RE.sub(lambda m: (m.group(1) or "") + "[REDACTED]", text)


def clip(text, n=90):
    text = redact(text.strip())
    return text if len(text) <= n else text[: n - 1] + "…"


# ---------------------------------------------------------------- acquire
def acquire(target, max_commits, notes):
    """Return (repo_path, github_slug, cleanup_dir)."""
    gh = re.match(r"https?://github\.com/([^/\s]+)/([^/\s#?]+)", target)
    if gh:
        slug = f"{gh.group(1)}/{gh.group(2).removesuffix('.git')}"
        tmp = tempfile.mkdtemp(prefix="skillyfile_")
        dest = os.path.join(tmp, "repo")
        try:
            subprocess.run(
                ["git", "clone", "--quiet", f"--depth={max_commits}",
                 f"https://github.com/{slug}.git", dest],
                check=True, capture_output=True, text=True, timeout=300)
        except FileNotFoundError:
            sys.exit("ERROR: git is not installed. Provide a local path or a zip instead.")
        except subprocess.CalledProcessError as e:
            sys.exit(f"ERROR: clone failed ({e.stderr.strip()[:200]}). "
                     "Check the URL is public and network is available, or provide a local path/zip.")
        except subprocess.TimeoutExpired:
            sys.exit("ERROR: clone timed out after 300s. Provide a local path or zip instead.")
        notes.append(f"Cloned last {max_commits} commits of {slug} into a temp dir.")
        return dest, slug, tmp

    if target.lower().endswith(".zip"):
        if not os.path.isfile(target):
            sys.exit(f"ERROR: zip not found: {target}")
        tmp = tempfile.mkdtemp(prefix="skillyfile_")
        with zipfile.ZipFile(target) as z:
            for member in z.namelist():   # block path traversal
                dest = os.path.realpath(os.path.join(tmp, member))
                if not dest.startswith(os.path.realpath(tmp) + os.sep):
                    sys.exit(f"ERROR: unsafe path in zip: {member}")
            z.extractall(tmp)
        entries = [e for e in os.listdir(tmp) if not e.startswith("__MACOSX")]
        root = os.path.join(tmp, entries[0]) if len(entries) == 1 and \
            os.path.isdir(os.path.join(tmp, entries[0])) else tmp
        notes.append("Unzipped into a temp dir.")
        return root, None, tmp

    if not os.path.isdir(target):
        sys.exit(f"ERROR: not a folder, GitHub URL, or zip: {target}")
    return os.path.abspath(target), None, None


# ---------------------------------------------------------------- git
def git(repo, *args):
    env = dict(os.environ, GIT_OPTIONAL_LOCKS="0", GIT_TERMINAL_PROMPT="0")
    try:
        r = subprocess.run(["git", "-c", "safe.directory=*", "-c", "core.fsmonitor=false", "-C", repo, *args], capture_output=True,
                           text=True, errors="replace", env=env, timeout=120)
        return r.stdout if r.returncode == 0 else None
    except (FileNotFoundError, subprocess.TimeoutExpired):
        return None


def github_slug_from_remote(repo):
    url = git(repo, "config", "--get", "remote.origin.url") or ""
    m = re.search(r"github\.com[:/]([^/\s]+)/([^/\s]+?)(\.git)?\s*$", url.strip())
    return f"{m.group(1)}/{m.group(2)}" if m else None


def normalise_subject(s):
    s = s.lower()
    s = re.sub(r"\(#?\d+\)|#\d+", "", s)                 # PR/issue refs
    s = re.sub(r"\bv?\d+(\.\d+)+\S*", "<ver>", s)         # versions
    s = re.sub(r"\b[0-9a-f]{7,40}\b", "<sha>", s)         # hashes
    s = re.sub(r"\d+", "<n>", s)
    s = re.sub(r"[^\w<>:\s-]", " ", s)
    words = s.split()
    return " ".join(words[:3]) if words else ""


def history(repo, max_commits):
    if not os.path.isdir(os.path.join(repo, ".git")) and git(repo, "rev-parse", "--git-dir") is None:
        return None
    raw = git(repo, "log", f"-n{max_commits}", "--no-merges", "--no-renames", "--name-only",
              "--format=@@@%H|%ad|%s", "--date=short")
    if raw is None:
        return None
    commits = []
    for block in raw.split("@@@")[1:]:
        lines = [l for l in block.splitlines() if l.strip()]
        sha, date, subj = (lines[0].split("|", 2) + ["", ""])[:3]
        commits.append((date, subj, lines[1:]))
    if not commits:
        return {"count": 0}
    file_changes = collections.Counter()
    subjects = collections.Counter()
    ctypes = collections.Counter()
    pairs = collections.Counter()
    for date, subj, files in commits:
        file_changes.update(files)
        subjects[normalise_subject(subj)] += 1
        m = re.match(r"^(\w+)(\(.+?\))?!?:", subj)
        if m:
            ctypes[m.group(1).lower()] += 1
        if 2 <= len(files) <= MAX_COCHANGE_FILES:
            fs = sorted(set(files))
            for i in range(len(fs)):
                for j in range(i + 1, len(fs)):
                    pairs[(fs[i], fs[j])] += 1
    dates = sorted(d for d, _, _ in commits if d)
    return {
        "count": len(commits), "first": dates[0] if dates else "?",
        "last": dates[-1] if dates else "?",
        "files": file_changes.most_common(15),
        "subjects": [(s, n) for s, n in subjects.most_common(15) if n >= 3],
        "types": ctypes.most_common(10),
        "pairs": [(p, n) for p, n in pairs.most_common(10) if n >= 3],
    }


# ---------------------------------------------------------------- github API
def github_items(slug, notes):
    """One anonymous request (60/h limit): last 100 issues+PRs."""
    url = f"https://api.github.com/repos/{slug}/issues?state=all&per_page=100"
    req = urllib.request.Request(url, headers={
        "Accept": "application/vnd.github+json", "User-Agent": "skillyfile-scan"})
    try:
        with urllib.request.urlopen(req, timeout=20) as r:
            data = json.load(r)
    except urllib.error.HTTPError as e:
        why = "rate limit hit" if e.code in (403, 429) else f"HTTP {e.code} (private or missing repo?)"
        notes.append(f"Issues/PRs skipped: {why}.")
        return None
    except Exception as e:  # network off, DNS, proxy
        notes.append(f"Issues/PRs skipped: no network access ({type(e).__name__}).")
        return None
    issues = [d for d in data if "pull_request" not in d]
    prs = [d for d in data if "pull_request" in d]
    labels = collections.Counter(l["name"] for d in data for l in d.get("labels", []))
    return {
        "issues": len(issues), "prs": len(prs),
        "labels": labels.most_common(12),
        "issue_titles": [(t, n) for t, n in collections.Counter(
            normalise_subject(d["title"]) for d in issues).most_common(10) if n >= 2],
        "pr_titles": [(t, n) for t, n in collections.Counter(
            normalise_subject(d["title"]) for d in prs).most_common(10) if n >= 2],
    }


# ---------------------------------------------------------------- files
def walk(repo):
    for root, dirs, files in os.walk(repo):
        dirs[:] = sorted(d for d in dirs if d not in SKIP_DIRS and not d.startswith(".")
                         or d in (".github", ".claude", ".husky", ".circleci", ".gitlab"))
        for f in sorted(files):
            yield os.path.join(root, f)


def rel(repo, p):
    return os.path.relpath(p, repo).replace(os.sep, "/")


def read_text(path):
    try:
        if os.path.getsize(path) > MAX_FILE_BYTES:
            return None
        with open(path, "r", encoding="utf-8", errors="strict") as fh:
            return fh.read()
    except (UnicodeDecodeError, OSError):
        return None


def scan_files(repo):
    ext_count = collections.Counter()
    top_dirs = collections.Counter()
    manifests = collections.Counter()
    high_signal = []
    skipped_secrets = 0
    todos = collections.Counter()
    todo_samples = []
    windows = collections.defaultdict(list)
    package_scripts, make_targets, workflows = {}, {}, {}
    total = scanned = 0
    total_bytes = 0

    for path in walk(repo):
        total += 1
        name = os.path.basename(path)
        r = rel(repo, path)
        if SECRET_FILE_RE.search(name):
            skipped_secrets += 1
            continue
        ext = os.path.splitext(name)[1].lower()
        ext_count[ext or name] += 1
        top_dirs[r.split("/")[0] if "/" in r else "(root)"] += 1
        try:
            total_bytes += os.path.getsize(path)
        except OSError:
            pass
        if name in ("package.json", "pyproject.toml", "go.mod", "Cargo.toml", "pom.xml", "composer.json"):
            manifests[name] += 1
        is_hs = HIGH_SIGNAL_NAMES.match(name) or r.startswith(HIGH_SIGNAL_DIRS) or \
            r.startswith((".github/", ".claude/", ".husky/", ".circleci/", ".gitlab/"))
        if ext not in TEXT_EXT and not is_hs:
            continue
        if scanned >= MAX_FILES_SCANNED:
            continue
        text = read_text(path)
        if text is None:
            continue
        scanned += 1
        lines = text.splitlines()
        if is_hs:
            high_signal.append((r, len(lines)))
        if name == "package.json":
            try:
                s = json.loads(text).get("scripts", {})
                if s:
                    package_scripts[r] = list(s.items())[:15]
            except (ValueError, AttributeError):
                pass
        if name.lower() in ("makefile", "justfile"):
            t = re.findall(r"^([A-Za-z0-9_.-]+):(?!=)", text, re.M)
            if t:
                make_targets[r] = t[:20]
        if r.startswith(".github/workflows/") and ext in (".yml", ".yaml"):
            jobs_part = re.split(r"^jobs:\s*$", text, maxsplit=1, flags=re.M)
            jobs = re.findall(r"^  ([A-Za-z0-9_-]+):\s*$", jobs_part[1], re.M) if len(jobs_part) > 1 else []
            flags = [f for f, pat in (("manual-trigger", r"workflow_dispatch"),
                                      ("schedule", r"^\s*schedule:"),
                                      ("approval-env", r"^\s*environment:"))
                     if re.search(pat, text, re.M)]
            workflows[r] = (jobs[:10], flags)
        # TODOs
        for i, line in enumerate(lines, 1):
            m = re.search(r"(?:#|//|--|/\*|^\s*\*|<!--)\s*(TODO|FIXME|HACK|XXX)\b[:\s]*(.*)", line)
            if m:
                todos[r.split("/")[0] if "/" in r else "(root)"] += 1
                if len(todo_samples) < 12 and m.group(2).strip():
                    todo_samples.append(f"{r}:{i} {m.group(1)} {clip(m.group(2), 70)}")
        # duplicate windows (code only)
        if ext in CODE_EXT:
            norm = [(i, re.sub(r"\s+", " ", l.strip())) for i, l in enumerate(lines, 1)]
            norm = [(i, l) for i, l in norm if len(l) > 3 and not re.fullmatch(r"[{}()\[\];,]+", l)
                    and not l.startswith(("import ", "from ", "#include", "using ", "//", "#", "*", "/*"))]
            for k in range(len(norm) - DUP_WINDOW + 1):
                chunk = "\n".join(l for _, l in norm[k:k + DUP_WINDOW])
                h = hashlib.md5(chunk.encode()).hexdigest()
                windows[h].append((r, norm[k][0], norm[k][1]))

    # collapse duplicate windows into groups by location set
    groups = {}
    for h, locs in windows.items():
        files = {f for f, _, _ in locs}
        if len(locs) < 2:
            continue
        key = tuple(sorted(files))
        g = groups.setdefault(key, {"hits": 0, "where": locs[:4], "preview": locs[0][2]})
        g["hits"] += 1
    dups = sorted(groups.items(), key=lambda kv: (-len(kv[0]), -kv[1]["hits"]))[:60]

    return {
        "total": total, "scanned": scanned, "bytes": total_bytes,
        "ext": ext_count.most_common(10), "dirs": top_dirs.most_common(15),
        "manifests": manifests, "high_signal": rank_high_signal(high_signal),
        "skipped_secrets": skipped_secrets, "todos": todos.most_common(10),
        "todo_samples": todo_samples, "dups": dups,
        "package_scripts": package_scripts, "make_targets": make_targets,
        "workflows": workflows, "capped": scanned >= MAX_FILES_SCANNED,
    }


# ---------------------------------------------------------------- report
def rank_high_signal(items, limit=30):
    """Root process files and automation first, docs last; skip assets."""
    def tier(path):
        name = path.rsplit("/", 1)[-1].lower()
        if "/" not in path or name.startswith(("readme", "contributing")):
            return 0
        if name in ("makefile", "justfile", "package.json", "dockerfile", "docker-compose.yml", "taskfile.yml"):
            return 1
        if path.startswith((".github/", ".claude/", ".husky/", ".circleci/", ".gitlab/")):
            return 1
        if path.startswith(("scripts/", "tools/", "bin/", "runbooks/")):
            return 2
        return 3
    items = [(p, n) for p, n in items
             if not p.lower().endswith((".svg", ".png", ".jpg", ".css", ".lock"))]
    ranked = sorted(items, key=lambda x: (tier(x[0]), x[0]))
    # docs/ can hold hundreds of pages: keep only the shortest few (guides, runbooks)
    core = [x for x in ranked if tier(x[0]) < 3]
    docs = sorted((x for x in ranked if tier(x[0]) == 3), key=lambda x: x[1])[:8]
    keep = (core + docs)[:limit]
    return keep, len(ranked) - len(keep)


def report(target, repo, fs, hist, api, notes):
    o = [f"# Repo scan: {target}", ""]
    mb = fs["bytes"] / 1_048_576
    o += ["## 1. Map",
          f"- Files: {fs['total']} ({mb:.1f} MB), text files scanned: {fs['scanned']}"
          + (" (capped)" if fs["capped"] else ""),
          "- Top extensions: " + ", ".join(f"{e} {n}" for e, n in fs["ext"]),
          "- Top-level folders (files): " + ", ".join(f"{d} {n}" for d, n in fs["dirs"])]
    multi = {k: v for k, v in fs["manifests"].items() if v > 1}
    if multi:
        o.append("- Monorepo hint: " + ", ".join(f"{v}× {k}" for k, v in multi.items()))
    if fs["skipped_secrets"]:
        o.append(f"- Secret-looking files skipped (not opened): {fs['skipped_secrets']}")
    o.append("")

    o.append("## 2. High-signal files (read these first)")
    hs, more = fs["high_signal"]
    o += [f"- {p} ({n} lines)" for p, n in hs] or ["- none found"]
    if more:
        o.append(f"- …and {more} more (mostly docs); open only if the above point there")
    for p, scripts in fs["package_scripts"].items():
        o.append(f"- scripts in {p}: " + "; ".join(f"`{k}`: {clip(v, 50)}" for k, v in scripts))
    for p, t in fs["make_targets"].items():
        o.append(f"- targets in {p}: " + ", ".join(t))
    for p, (jobs, flags) in fs["workflows"].items():
        o.append(f"- workflow {p}: jobs [{', '.join(jobs)}]" + (f" flags [{', '.join(flags)}]" if flags else ""))
    o.append("")

    o.append("## 3. Git history")
    if not hist:
        o.append("- Not available (see notes).")
    elif hist["count"] == 0:
        o.append("- Repository has no commits.")
    else:
        o.append(f"- {hist['count']} commits analysed, {hist['first']} → {hist['last']}")
        if hist["types"]:
            o.append("- Conventional types: " + ", ".join(f"{t} {n}" for t, n in hist["types"]))
        o.append("- Most-changed files:")
        o += [f"  - {f} ({n})" for f, n in hist["files"]]
        if hist["subjects"]:
            o.append("- Recurring commit subjects (first 3 words, normalised, ≥3×):")
            o += [f"  - \"{s}\" ×{n}" for s, n in hist["subjects"]]
        if hist["pairs"]:
            o.append("- Files that change together (≥3×):")
            o += [f"  - {a} + {b} ×{n}" for (a, b), n in hist["pairs"]]
    o.append("")

    o.append("## 4. Issues & PRs (last 100, public API)")
    if not api:
        o.append("- Not available (see notes).")
    else:
        o.append(f"- {api['issues']} issues, {api['prs']} PRs")
        if api["labels"]:
            o.append("- Labels: " + ", ".join(f"{l} {n}" for l, n in api["labels"]))
        for title, key in (("Recurring issue titles", "issue_titles"), ("Recurring PR titles", "pr_titles")):
            if api[key]:
                o.append(f"- {title}: " + ", ".join(f"\"{t}\" ×{n}" for t, n in api[key]))
    o.append("")

    o.append(f"## 5. Duplicate code ({DUP_WINDOW}+ matching lines)")
    is_mig = lambda files: all(re.search(r"(^|/)migrations?/", f) for f in files)
    code = [d for d in fs["dups"] if not is_mig(d[0])]
    mig = [d for d in fs["dups"] if is_mig(d[0])]
    if not fs["dups"]:
        o.append("- none found")
    for files, g in code[:12]:
        where = ", ".join(f"{f}:{ln}" for f, ln, _ in g["where"])
        scope = "within 1 file" if len(files) == 1 else f"{len(files)} files"
        o.append(f"- {scope}, {g['hits']} windows — {where} — `{clip(g['preview'], 60)}`")
    if mig:
        nfiles = len({f for files, _ in mig for f in files})
        o.append(f"- Migrations: {len(mig)} repeated blocks across {nfiles} migration files "
                 "(re-definitions are expected; read as a recurring migration pattern). Top 3:")
        for files, g in mig[:3]:
            o.append(f"  - {len(files)} files, {g['hits']} windows — `{clip(g['preview'], 60)}`")
    o.append("")

    o.append("## 6. TODO / FIXME / HACK")
    if not fs["todos"]:
        o.append("- none found")
    else:
        o.append("- By folder: " + ", ".join(f"{d} {n}" for d, n in fs["todos"]))
        o += [f"  - {s}" for s in fs["todo_samples"]]
    o.append("")

    if notes:
        o.append("## Notes")
        o += [f"- {n}" for n in notes]
    return "\n".join(o) + "\n"


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("target")
    ap.add_argument("--out", help="write report here (must be outside the repo)")
    ap.add_argument("--max-commits", type=int, default=500)
    ap.add_argument("--no-api", action="store_true", help="skip GitHub issues/PRs")
    a = ap.parse_args()
    notes = []
    repo, slug, cleanup = acquire(a.target, a.max_commits, notes)
    try:
        if a.out:
            out_abs = os.path.realpath(a.out)
            if out_abs.startswith(os.path.realpath(repo) + os.sep):
                sys.exit("ERROR: --out must be outside the repo (the scanner never writes into it).")
        fs = scan_files(repo)
        hist = history(repo, a.max_commits)
        if hist is None:
            notes.append("No git history: " + ("zip has no .git folder." if a.target.lower().endswith(".zip")
                                               else "no .git folder, or git is not installed/readable."))
        slug = slug or github_slug_from_remote(repo)
        api = None
        if a.no_api:
            notes.append("Issues/PRs skipped (--no-api).")
        elif slug:
            api = github_items(slug, notes)
        else:
            notes.append("Issues/PRs skipped: no GitHub remote found.")
        text = report(a.target, repo, fs, hist, api, notes)
        if a.out:
            with open(a.out, "w", encoding="utf-8") as fh:
                fh.write(text)
            print(f"Report written to {a.out} ({len(text.splitlines())} lines)")
        else:
            sys.stdout.write(text)
    finally:
        if cleanup:
            shutil.rmtree(cleanup, ignore_errors=True)


if __name__ == "__main__":
    main()
