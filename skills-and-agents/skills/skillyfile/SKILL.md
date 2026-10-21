---
name: skillyfile
description: Reads an uploaded or referenced file (docs, SOPs, notes, emails, spreadsheets, CSVs, logs, code, configs) and finds complex, repetitive tasks that could become Claude skills or agents, then proposes a ranked plan of up to 7 with names, short descriptions, and ready-to-paste --skill/--agent build prompts. Use when the user runs /skillyfile, or asks what in a file could be automated, turned into skills or agents, or which repetitive work a document, dataset, or codebase reveals. Not for plain summaries or edits of a file.
---

# Skillyfile

Turn a file into a ranked plan of skills and agents worth building.

## Workflow

Copy this checklist and track progress:

```
- [ ] 1. Get the file
- [ ] 2. Read and map it
- [ ] 3. Extract candidate tasks
- [ ] 4. Classify each (prompt / skill / agent)
- [ ] 5. Score and rank (max 7)
- [ ] 6. Write the plan + build prompts
```

### 1. Get the file

- Use every file attached to the message or referenced by path or URL. Several files are analysed together as one body of work.
- No file found → ask for one and stop. Don't guess from the request text.
- Can't open it (unsupported format, access denied, empty) → say which file and why, and ask for another format or a pasted excerpt.

### 2. Read and map it

- Docs and notes: read the whole file. Note roles, recurring meetings or reports, step lists, checklists, templates, and handoffs.
- Spreadsheets, CSV, logs: inspect the columns, row count, and repeated row patterns (same action, category, or status recurring). Sample rather than reading every row once a file passes about 2,000 rows, and say that you sampled.
- Code and configs: look for repeated scripts, manual steps in READMEs, CI jobs, TODOs, and copy-pasted logic.

For the signals to look for, see [references/detection-signals.md](references/detection-signals.md).

### 3. Extract candidate tasks

A task qualifies only if it passes the three tests in detection-signals.md: **recurrence** (it recurs, or shows up many times), **substance** (several steps, judgement, or specialised know-how), and **stability** (the procedure is mostly the same each time). For each one, record:
- What the task is, in the user's own terms
- Evidence: a short quote, section, column, or file/line it comes from
- How often it seems to happen, and roughly how much effort it takes

Drop one-off tasks and anything Claude already does well from a single plain request.

### 4. Classify

Use the per-file-type "Classify" notes in detection-signals.md and the rules in [references/skill-vs-agent.md](references/skill-vs-agent.md). Pick the lightest form that works:
- **Prompt**: mention it in one line, but don't build it as an item
- **Skill**: a repeatable procedure, format, or know-how used inside a chat
- **Agent**: needs autonomy over many steps, its own tools or MCP servers, a loop, or to run unattended

Default to a skill whenever a skill would do the job.

### 5. Score and rank

Value = frequency (1–3) × effort saved (1–3), using the scoring table in detection-signals.md. Label inferred frequencies as estimates. Sort by value from high to low and keep at most 7. Mark ⚡ **quick win** on items that are high value and simple to build. If two candidates overlap heavily, merge them.

### 6. Output

Use this template:

~~~markdown
## Skillyfile plan: <file name(s)>

<1–2 sentences: what the file shows about the user's work>

| # | Name | Type | What it does | Evidence | Value |
|---|------|------|--------------|----------|-------|
| 1 | `kebab-name` | Skill | One sentence | "quote" / section / column | 9 ⚡ |

**Not worth building (a plain prompt is enough):** <optional, one line each>

### Build prompts
Paste each into a new chat in this project:

**1. `kebab-name`**
```
--skill <name>: <what it does>. Triggers: <example phrases>. Input: <files/data>. Output: <format>. Context from <file>: <key facts, steps, rules found>.
```

Which would you like to build first?
~~~

Rules:
- Names must be kebab-case, lowercase, at most 64 characters, and must not contain "claude" or "anthropic". Prefer gerund or action names (`drafting-guest-replies`).
- Each build prompt must stand alone: include the context you found in the file, because the new chat won't have the file.
- Agent prompts also state the target platform if it's known (Claude Code subagent, Agent SDK, API) and which tools the agent needs.
- Never copy personal data, credentials, or secrets from the file into the plan or the prompts. Describe them generically ("guest email", "API key").
- If nothing qualifies, say so plainly and explain why. Never pad the list.
