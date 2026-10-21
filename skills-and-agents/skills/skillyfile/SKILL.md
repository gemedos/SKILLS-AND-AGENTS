---
name: skillyfile
description: Reads an uploaded or referenced file (docs, SOPs, notes, emails, spreadsheets, CSVs, logs, code, configs) or a whole code repository (local folder, public GitHub URL, or zip) and finds complex, repetitive tasks that could become Claude skills or agents, plus CLAUDE.md rules, slash commands or hooks for repos. Applies a size threshold so tasks too small to be worth a skill are flagged, not proposed. Proposes a ranked plan of up to 7 with names, short descriptions, and ready-to-paste --skill/--agent build prompts. Use when the user runs /skillyfile, or asks what in a file or repo could be automated or turned into skills or agents. Not for plain summaries, code reviews, or explaining a repo.
---

# Skillyfile

Turn a file into a ranked plan of skills and agents worth building.

## Workflow

Copy this checklist and track progress:

```
- [ ] 1. Get the file (a folder, repo URL, or repo zip → Repo mode)
- [ ] 2. Read and map it
- [ ] 3. Extract candidate tasks
- [ ] 4. Apply the skill threshold (gates → score → verdict → confidence)
- [ ] 5. Merge small items, classify, rank (max 7 ✅/⚖️)
- [ ] 6. Write the plan + build prompts (✅ only)
```

### 1. Get the file

- Use every file attached to the message or referenced by path or URL. Several files are analysed together as one body of work.
- No file found → ask for one and stop. Don't guess from the request text.
- Can't open it (unsupported format, access denied, empty) → say which file and why, and ask for another format or a pasted excerpt.
- The input is a code repository (a folder with source code, a `github.com/<owner>/<repo>` URL, or a zip of a project) → follow **Repo mode** below for steps 1–2, then continue at step 3.

### 2. Read and map it

- Docs and notes: read the whole file. Note roles, recurring meetings or reports, step lists, checklists, templates, and handoffs.
- Spreadsheets, CSV, logs: inspect the columns, row count, and repeated row patterns (same action, category, or status recurring). Sample rather than reading every row once a file passes about 2,000 rows, and say that you sampled.
- Code and configs: look for repeated scripts, manual steps in READMEs, CI jobs, TODOs, and copy-pasted logic.

For the signals to look for, see [references/detection-signals.md](references/detection-signals.md).

### Repo mode

The repo is **read-only**: never edit, format, commit, install dependencies, or run code from it. Read with plain file reads and the scanner only.

1. **Scan.** Run the bundled scanner (stdlib only, Python 3.9+). It never writes into the repo:
   ```bash
   python scripts/scan_repo.py <path | https://github.com/owner/repo | repo.zip> --out <scratch>/scan.md
   ```
   - Put `--out` outside the repo, in a scratch or temp folder.
   - A URL is cloned (last 500 commits) into a temp dir and deleted afterwards. If the clone fails (no network, private repo), ask for a local path or a zip.
   - Add `--no-api` to skip GitHub issues/PRs. Without it, the scanner makes one anonymous API call, which is limited to 60 per hour.
2. **Read the report** using [references/repo-signals.md](references/repo-signals.md). Note every gap the report states (no history, no issues, sampled) and repeat it in the plan.
3. **Open only the high-signal files** the report lists, about 10–15 at most: CLAUDE.md/AGENTS.md, README, the hottest docs, scripts, and workflows. Read source code only to confirm a specific candidate.
4. **Candidates** also include repo-native forms: a CLAUDE.md addition, a slash command, or a hook (see the table in repo-signals.md). Use them when they're lighter than a skill.
5. **In the plan,** the Evidence column cites report facts ("changed in 20 of 70 commits", "same helper in 3 edge functions"). The Type column can be `CLAUDE.md`, `Command`, or `Hook` as well as `Skill` or `Agent`.

### 3. Extract candidate tasks

Find tasks that pass the three tests in detection-signals.md: **recurrence**, **substance**, and **stability**. For each one, record:
- What the task is, in the user's own terms
- Evidence: a short quote, section, column, file/line, or report fact
- How often it seems to happen, and roughly how much effort it takes

Collect generously here. Filtering happens in step 4.

### 4. Apply the skill threshold

**Every candidate must go through [references/skill-threshold.md](references/skill-threshold.md).** Don't propose small skills. Many tiny skills crowd the skill listing and rarely trigger.

1. **Gates:** it recurs, it has a knowledge gap (Claude would get it wrong without help), and it's a coherent unit of work. If any gate fails, it's ❌. Name the lighter alternative.
2. **Score** the six criteria from 0 to 2 each (out of 12), and apply the size check.
3. **Verdict:** 8–12 is ✅ build, 5–7 is ⚖️ borderline, 0–4 is ❌ not worth a skill.
4. **Confidence:** High, Medium or Low. Mark **❓ Unsure** when confidence is Low or the score is 1 point from a band edge, and say what would settle it.

### 5. Merge, classify, rank

- **Merge** related small candidates with the same trigger context into one coherent unit, then re-score it. Split anything that's too broad.
- **Classify** each ✅ item using [references/skill-vs-agent.md](references/skill-vs-agent.md), and the repo-native table in repo-signals.md for repos. An agent also needs an agent trigger (its own tools, autonomy, a loop, or running unattended).
- **Rank** ✅ items by score, then ⚖️ items. Keep at most 7 ✅ + ⚖️ items in total. Mark ⚡ **quick win** on a ✅ that is simple to build.

### 6. Output

Use this template:

~~~markdown
## Skillyfile plan: <file or repo name>

<1–2 sentences: what the file shows about the user's work. Mention any gaps: sampled, no history, etc.>

### ✅ Worth building
| # | Name | Type | What it does | Evidence | Score | Confidence |
|---|------|------|--------------|----------|-------|------------|
| 1 | `kebab-name` | Skill | One sentence | "quote" / section / report fact | 10/12 ⚡ | High |

### ⚖️ Borderline: your call
| Name | Score | For | Against | Suggestion |
|------|-------|-----|---------|------------|
| `kebab-name` | 6/12 ❓ | one reason | one reason | Merge into #1 / make it a slash command |

### ❌ Not worth a skill
- <task>: <why, in a few words> → <lighter alternative, e.g. "add to CLAUDE.md: …">

### Build prompts (✅ only)
Paste each into a new chat in this project:

**1. `kebab-name`**
```
--skill <name>: <what it does>. Triggers: <example phrases>. Input: <files/data>. Output: <format>. Context from <file>: <key facts, steps, rules, gotchas found>.
```

### ❓ To settle the unsure items
1. <question, e.g. "How often do you run the Excel migration?">

Which would you like to build first?
~~~

Rules:
- Names must be kebab-case, lowercase, at most 64 characters, and must not contain "claude" or "anthropic". Prefer gerund or action names (`drafting-guest-replies`).
- Each build prompt must stand alone: include the context you found in the file, because the new chat won't have the file.
- Agent prompts (and hooks/commands in repo mode) also state the target platform if it's known (Claude Code subagent, Agent SDK, API) and which tools the agent needs.
- Never copy personal data, credentials, or secrets from the file into the plan or the prompts. Describe them generically ("guest email", "API key").
- Show the score for every ✅ and ⚖️ item, so the user can check the reasoning.
- If nothing reaches ✅, say so plainly, keep the ⚖️ and ❌ sections, and don't pad the list. A short plan that says "only one thing here is worth a skill" is a good result.
