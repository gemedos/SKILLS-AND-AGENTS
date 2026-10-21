# Skill threshold

When a candidate is big enough to become a skill, and what to suggest when it isn't. Apply it to every candidate before it goes in the plan.

## Contents
- Why there is a threshold
- Step 1: Gates (pass all three)
- Step 2: Substance score (0–12)
- Step 3: Verdict bands
- Step 4: Confidence
- Merging and splitting
- Lighter alternatives
- Worked examples
- Sources

## Why there is a threshold

These points come from Anthropic and agentskills.io guidance (see Sources):
- **Small tasks don't trigger skills.** Claude only consults a skill for work it can't easily do on its own. "Simple, one-step queries … may not trigger a skill even if the description matches perfectly." A tiny skill may never be used.
- **A skill must beat no skill.** Skills are evaluated against a no-skill baseline. "If the agent already handles the entire task well without the skill, the skill may not be adding value."
- **Every skill costs context.** Each name and description sits in the skill listing, which has a budget of about 1% of context. When it overflows, descriptions get dropped. Many small skills crowd out the useful ones.
- **Skills are coherent units of work.** "Too narrowly scoped skills force multiple skills to load for a single task"; too broad ones are "hard to activate precisely".
- **Skills hold procedures, not facts.** Create a skill "when you keep pasting the same instructions, checklist, or multi-step procedure", or "when a section of CLAUDE.md has grown into a procedure rather than a fact". Rules that must hold every time belong in a hook.

## Step 1: Gates (pass all three)

If a candidate fails any gate, it is **not a skill**. Say which lighter form fits instead (see "Lighter alternatives").

| Gate | Passes when | Typical fail → instead |
|---|---|---|
| **G1 Recurring** | It happens at least about monthly and will keep happening | A one-off project → just do it (prompt) |
| **G2 Knowledge gap** | Without instructions, Claude would get it wrong or do it inconsistently, because it needs project-specific rules, gotchas, formats, schemas or steps | Claude already does it well from a one-line request → prompt |
| **G3 Coherent unit** | It is a whole piece of work with an input and an output, not a single fact, rule or step | A single rule or fact → CLAUDE.md line. Must happen on every event → hook |

## Step 2: Substance score (0–12)

Score each criterion 0, 1 or 2, using only evidence from the file or repo scan. If you have to infer a score, record it as inferred (see Step 4).

| # | Criterion | 0 | 1 | 2 |
|---|---|---|---|---|
| 1 | **Steps** | 1 step | 2–3 steps | 4+ steps, or branching (if/then) |
| 2 | **Knowledge to capture** | None beyond common sense | A few rules or conventions | Rules + gotchas + templates, schemas or examples |
| 3 | **Cost of a mistake** | Cosmetic | Rework or embarrassment | Money, legal/tax, data loss, production or guest-facing |
| 4 | **Frequency** | About monthly | Weekly | Daily, or 100+ instances |
| 5 | **Effort per run today** | Under 10 min | 10–60 min | Over 60 min, or repeated corrections |
| 6 | **Bundled resources** | None needed | A template or reference doc | A deterministic script or validator |

**Size check (heuristic).** Estimate the SKILL.md the candidate would need. If the core instructions fit in about 20 lines and need no references or scripts, treat it as too small and cap the score at 7, unless criterion 3 scores 2. At the other end, if it would need more than about 500 lines of core instructions, split it (see "Merging and splitting").

## Step 3: Verdict bands

| Score | Verdict | What the plan says |
|---|---|---|
| **8–12** | ✅ **Build a skill** | Include it with a build prompt. |
| **5–7** | ⚖️ **Borderline** | List it as "your call". Give the one reason for and the one reason against. Suggest merging it into a related skill, or a lighter form. No build prompt unless the user asks. |
| **0–4** | ❌ **Not worth a skill** | One line: what it is, and the lighter alternative ("add to CLAUDE.md: …", "make it a slash command", "use a formula"). |

Agents: an agent candidate must first score ✅ as a unit of work *and* meet an agent trigger in skill-vs-agent.md (its own tools, autonomy, a loop, or running unattended). Otherwise, recommend a skill.

## Step 4: Confidence

Label every ✅ and ⚖️ verdict:
- **High**: frequency and steps come straight from the evidence (dates, counts, written procedures, commit history).
- **Medium**: one of criteria 4 or 5 is inferred.
- **Low**: two or more criteria are inferred, or the evidence is thin (a single mention, a sampled file).

When confidence is **Low**, or the score is within 1 point of a band edge (4/5 or 7/8), mark it **❓ Unsure** and say what would settle it: "How often do you do this?" or "Does Claude already get this right without help?" Ask at most 2–3 such questions at the end of the plan. Never present a guess as a fact.

## Merging and splitting
- **Merge** small candidates that share the same trigger context and domain into one coherent unit: "guest replies for check-in, parking and Wi-Fi" → one `drafting-guest-replies` skill. Re-score the merged unit. Merging often lifts several ⚖️ or ❌ items into one ✅.
- **Don't merge** things with different triggers or different users, even if they're in the same file.
- **Split** if one candidate would need more than about 500 lines of core instructions, or covers clearly separate jobs. For example, "query the database" and "administer the database" are separate jobs.

## Lighter alternatives

| The candidate is… | Suggest |
|---|---|
| A fact or rule Claude should always know | A line in CLAUDE.md (or Project instructions in claude.ai) |
| A short prompt you rerun, one step, little knowledge | A saved prompt or slash command |
| Something that must happen every time, deterministically | A hook, or a script or CI step |
| Pure calculation or formatting with no judgement | A formula, macro or script (not Claude) |
| Background knowledge for a body of work | Project knowledge, not a skill |
| Already covered by an existing skill or tool | Mention the existing one |

## Worked examples

| Candidate | Gates | Scores (1–6) | Total | Verdict |
|---|---|---|---|---|
| "Reply to the check-in-time question" | G2 fails (one fact) | — | — | ❌ An FAQ line in CLAUDE.md or Project instructions |
| "Guest replies in house style for 12 recurring intents" | pass | 1, 2, 2, 2, 1, 1 | 9 | ✅ High |
| "Monthly owner settlement from bookings CSV" | pass | 2, 2, 2, 0, 2, 2 | 10 | ✅ High |
| "Run lint before every commit" | G3 fails (must happen on every event) | — | — | ❌ Hook |
| "Rename exported files to a date pattern" | pass (weekly) | 1, 0, 0, 1, 0, 2 | 4 | ❌ Script |
| "Add a dashboard module (registry + icons + catalogue)" | pass | 2, 2, 1, 1, 1, 1 | 8 | ✅ Medium (frequency inferred from commits) |
| "Shared auth helper in edge functions" | G3 fails (a single rule) | — | — | ❌ CLAUDE.md line |

## Sources
- Claude Code skills docs: when to create a skill, CLAUDE.md vs skills, listing budget, hooks for must-hold rules. https://code.claude.com/docs/en/skills
- Anthropic skill-creator: "Claude only consults skills for tasks it can't easily handle on its own", and evaluating with-skill vs without-skill. https://github.com/anthropics/skills/tree/main/skills/skill-creator
- agentskills.io best practices: "Design coherent units", "Add what the agent lacks", "Aim for moderate detail", 500 lines / 5,000 tokens. https://agentskills.io/skill-creation/best-practices
- agentskills.io evaluating skills: the baseline comparison and cost/benefit delta. https://agentskills.io/skill-creation/evaluating-skills
- Skill authoring best practices: concise, under 500 lines, progressive disclosure. https://platform.claude.com/docs/en/agents-and-tools/agent-skills/best-practices
- Skills explained: skills vs prompts, projects, MCP and subagents. https://claude.com/blog/skills-explained
- The score bands, the ~20-line size check and the confidence rules are skillyfile's own heuristics built on these sources, not official Anthropic numbers.
