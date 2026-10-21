# Repo signals

How to read the `scan_repo.py` report and turn it into candidates. Use this together with detection-signals.md (sections "Code repositories" and "CI/CD, infra & configs").

## Contents
- Reading each report section
- Repo-native outputs (CLAUDE.md, slash commands, hooks)
- Monorepos
- Pitfalls

## Reading each report section

### 1. Map
- Use it to see the shape of the repo: frontend, backend, database, infra.
- A **monorepo hint** means you should analyse per package (see "Monorepos" below).
- **Secret-looking files skipped** is expected. Never open those files.

### 2. High-signal files
Read them in the order listed. What to look for:
- **CLAUDE.md / AGENTS.md** with rules like "every time you change X, also update Y". This is a repeated duty the team already wants automated. It's a strong candidate for a hook or a skill.
- **README "how to" sections:** setup, deploy, release, data loading. Manual sequences point to skills.
- **package.json scripts / Makefile targets:** each one-off script (`migrar-*`, `seed-*`, `import-*`) is a procedure that someone runs repeatedly with judgement around it. A script plus a skill is often the right shape: the skill explains when and how to run it, and how to check the result.
- **Workflows with `manual-trigger` or `approval-env` flags:** human gates. These point to a release skill, or an agent if the steps run without someone watching.
- **"Living documents"** (checklists, roadmaps, decision logs that must be kept up to date): maintaining them is recurring work.

### 3. Git history
- **Most-changed files:** where people spend their effort.
  - Docs and checklists at the top → a doc-upkeep skill or hook.
  - Registries or index files (`registro.ts`, `routes.ts`, `index.ts`) → a "scaffold a new X" skill.
- **Recurring commit subjects:**
  - `bump`, `update deps`, `release version` → a release or dependency skill. Check first whether a tool such as Dependabot or Renovate already covers it.
  - `fase N`, `feat(module)` → a phased roadmap. Each phase follows the same routine (code, migration, docs, deploy checklist).
  - `fix lint/types/mypy` → a hook (run the linter before commit).
- **Files that change together:** co-change pairs show one task spread across several files. Adding a module that always touches A + B + C is a textbook scaffold skill, and the pair list tells you which files it must update.
- Treat history from shallow clones (`--depth`) as a sample, not the full story.

### 4. Issues & PRs
- **Labels with high counts** (`bug`, `support`, `dependencies`) point to recurring workstreams.
- **Recurring titles** ("Bug: login fails…") point to triage or diagnosis skills.
- **Recurring PR titles from bots** are already automated. Don't propose them.
- If the section is unavailable (private repo, rate limit, no network), say so and rely on the other sections.

### 5. Duplicate code
- **Code duplicates across files** (the same helper in three handlers) → propose a **convention + scaffold skill** that tells Claude to reuse or extract the shared helper. Don't propose fixing the duplication itself; that's a one-off refactor.
- **"Within 1 file"** duplicates are usually tests or repeated markup. They're a weak signal.
- **Migrations line:** repeated blocks in migrations are re-definitions by design. When there are many, read them as "writing migrations is frequent and follows a pattern" → a `writing-<db>-migrations` skill (naming, idempotency, RLS or permissions, types regeneration).

### 6. TODO / FIXME / HACK
- Clusters in one area → known debt. That's a one-off job, not a skill, unless the same TODO wording repeats (for example "TODO: add translation") → a recurring task.
- Words in other languages can produce false positives (Spanish "TODO" means "all"). Check the sample text.

## Repo-native outputs

In repo mode, also consider these Claude Code options when they fit better than a skill or agent. Pick the lightest one that does the job:

| Fits when… | Propose | Notes |
|---|---|---|
| A rule Claude must always know in this repo (conventions, "never touch X", where docs live) | **CLAUDE.md addition** | Give the exact lines to add. If CLAUDE.md already exists, propose only the missing rules. |
| A short prompt the team reruns often in this repo ("update the deploy checklist", "write the phase summary") | **Slash command** (`.claude/commands/<name>.md`) | Lighter than a skill; suits a single step. |
| Something that must happen automatically on an event (format or lint after edits, block edits to protected files, remind to update a doc) | **Hook** (`.claude/settings.json`) | Deterministic. Describe the event (for example PostToolUse on Edit) and the command. |
| A procedure with know-how, templates, or scripts | **Skill** | As in file mode. |
| Multi-step work in its own context, or with its own tools | **Agent** (Claude Code subagent in `.claude/agents/`) | For example a reviewer or migration auditor. |

Build prompts for these use `--skill` (for skills, slash commands, CLAUDE.md additions, and hooks) or `--agent` (for subagents). In the prompt, say which repo-native form is intended.

## Monorepos
- Group candidates by package or app. Name them with the package prefix when they're specific to it (`web-adding-pages`).
- Candidates that span packages (release, shared migrations) are listed once, at the repo level.

## Pitfalls
- **Generated files** (`database.types.ts`, lockfiles) show up in the most-changed list because they're regenerated. Read them as "regeneration is part of a routine", not as hand-edited hotspots.
- **Vendor or bot noise:** ignore Dependabot, Renovate, and pre-commit-ci patterns when proposing work. Mention them as "already automated" instead.
- **One huge commit** can skew counts. Co-change pairs ignore commits touching more than 20 files for this reason.
- **Never quote** secrets, keys, project URLs with IDs, or personal data from the repo in the plan. Describe them generically.
