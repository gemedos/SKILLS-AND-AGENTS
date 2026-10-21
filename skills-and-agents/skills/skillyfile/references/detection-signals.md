# Detection signals

Patterns that reveal complex, repetitive work in files, and how each pattern usually classifies.

## Contents
- The three tests
- Universal signals (any file)
- Process docs & SOPs
- Meeting notes
- Email, chat & support exports
- Templates, contracts & forms
- Spreadsheets & trackers
- Event logs & exports (process-mining view)
- Code repositories
- CI/CD, infra & configs
- Prompt libraries & AI chat logs
- Calendars, decks & other files
- Measuring frequency and effort (evidence; scoring in skill-threshold.md)
- False positives & disqualifiers

## The three tests

A candidate must pass all three:

1. **Recurrence**: it happens again and again, either over time (weekly, per booking) or in volume (many rows or messages with the same shape).
2. **Substance**: it has several steps, needs judgement, or depends on rules or know-how. One-step work is a plain prompt.
3. **Stability**: the steps or rules stay mostly the same between runs. If each run is completely different, nothing reusable can be captured.

Then run the skill threshold (skill-threshold.md). Typical outcomes:

| Pattern | Usual type |
|---|---|
| Same steps + house rules/format, a human in the loop | **Skill** |
| Deterministic transform (clean, convert, compute) | **Skill with a script** |
| Must act across tools/systems, loop until done, or run unattended | **Agent** |
| Several skills that always run in sequence | **Agent** that uses those skills |
| Short and context-free | **Prompt** (mention only) |
| Fixed rules, no judgement, already scriptable | **Not Claude**: point to a formula, macro, or cron job |

## Universal signals (any file)
- **Time words:** "every Monday", "monthly", "each time", "whenever", "per guest/client/invoice", "at check-out".
- **Effort words:** "manually", "copy-paste", "re-type", "chase", "double-check", "always forget", "takes ages", "tedious".
- **Handoffs:** "export from X, import into Y", "send to", "forward to", "once approved". Data moving between applications is a classic automation sign.
- **Repeated structure:** the same headings, field lists, or message shape appearing three or more times.
- **Rules and exceptions:** "if… then…", "unless", "except when", "make sure to". This is know-how a skill can hold.
- **Quality gates:** review, approve, check, verify, reconcile. These can become validation loops inside a skill.

## Process docs & SOPs
**Signals**
- Numbered step lists, checklists ("aide-memoire" items), and decision branches
- Role tags (who does each step) and handoffs between roles
- Embedded templates, sample emails, required fields
- Hazards and controls, or compliance rules that must be applied every time
- Notes like "see attached", "use the latest version", which point to brittle manual lookups

**Classify**
- An SOP that one person follows in chat → **skill**. The steps become the workflow and the rules go into references/.
- An SOP that spans several systems (PMS, email, accounting) end to end → **agent**.
- Several SOPs sharing the same rules → one skill with domain reference files, not several skills.

**Example names:** `onboarding-new-owners`, `processing-check-outs`

## Meeting notes
**Signals**
- The same agenda items appearing across dates (status, KPIs, blockers)
- Action items that recur: "X to send report", "follow up with…"
- Decisions that keep getting re-explained, which is missing documented know-how
- The same numbers being quoted, suggesting a report someone builds by hand before each meeting

**Classify:** a recurring pre-meeting report → **skill**. Turning notes into actions, tickets, or emails → **skill**, or an **agent** if it should file tickets or send emails itself.

**Example names:** `preparing-weekly-ops-review`, `extracting-action-items`

## Email, chat & support exports
**Signals**
- Clusters of near-identical questions (group by intent: check-in time, invoices, parking)
- Replies that reuse the same paragraphs, which shows a template plus per-case details
- Long threads that follow the same lifecycle (request → info gathering → confirmation)
- Escalation patterns: the same issue being forwarded to the same person
- Tags, labels, or categories applied by hand

**How to measure:** count messages per intent cluster, and estimate the share of total volume and how many minutes each reply takes.

**Classify**
- Drafting replies in house style → **skill**, with a tone guide and an FAQ in references/.
- Triage + label + draft across an inbox or helpdesk → **agent** with email or helpdesk tools.
- Single-answer FAQs → **prompt** (or a knowledge doc).

**Example names:** `drafting-guest-replies`, `triaging-support-inbox`

**Privacy:** describe clusters by intent. Never quote names, emails, phone numbers, or booking IDs.

## Templates, contracts & forms
**Signals**
- Placeholders: `[NAME]`, `{{date}}`, `____`, highlighted fields
- Several filled-in copies that differ only in a few fields
- Clause libraries, or "choose option A/B" notes
- Forms that are re-keyed from another source

**Classify:** filling a template from data → **skill** (with a script if the format is .docx or .pdf). Reviewing contracts against a playbook → **skill** with the playbook in references/.

**Example names:** `generating-rental-contracts`, `reviewing-supplier-agreements`

## Spreadsheets & trackers
**Signals**
- Columns filled by hand in a consistent pattern (status, category, owner, notes)
- Values that look hand-computed (totals, percentages, dates + N days) where no formula exists
- Free-text columns that need classifying or normalising (mixed date formats, misspelt categories, duplicates)
- One tab per period (Jan, Feb…) with an identical layout, which is a recurring report
- Lookup work: the same IDs appearing in several sheets that must be matched or reconciled
- Rows that each represent one repeat of an action (one per booking, ticket, invoice)

**How to measure:** rows per period give frequency. The number of hand-edited columns per row gives effort.

**Classify**
- Clean, normalise, reconcile, report → **skill with a script** (pandas/openpyxl).
- Pulling fresh data from systems, updating the sheet, and notifying → **agent**.
- A single formula would solve it → **not Claude**. Suggest the formula.

**Example names:** `cleaning-booking-exports`, `building-monthly-occupancy-report`, `reconciling-payouts`

## Event logs & exports (process-mining view)
Treat any log with *case ID + activity + timestamp* as a process trace.

**Signals**
- **Variants:** the same sequence of activities repeating across many cases
- **Rework loops:** an activity happening twice or more in one case (re-send, re-check, reopen)
- **Bottlenecks:** long waits between the same two activities, usually where a manual step sits
- **Repeated errors or alerts** with the same message pattern

**Classify:** explaining or triaging the log on demand → **skill**. Watching continuously, triaging, and acting → **agent**.

**Example names:** `analysing-booking-funnel`, `triaging-error-logs`

## Code repositories
**Signals**
- **Duplicated code:** exact copies, near-duplicates (renamed variables), or copy-pasted functions. Ignore tiny fragments of one or two lines.
- READMEs or docs with manual multi-step procedures ("run A, edit B, then deploy")
- Clusters of TODO/FIXME/HACK on the same theme
- Repeated review comments or the same fix in many commits
- Generators or boilerplate creation (new endpoint, new component) that people do by hand

**Classify**
- Conventions plus a repeatable change (add an endpoint, write tests in house style) → **skill**.
- Exploring the whole codebase, multi-file refactors, or review passes in their own context → **agent** (Claude Code subagent).
- Pure boilerplate → **skill with a script/template**.

**Example names:** `adding-api-endpoints`, `reviewing-pull-requests`

## CI/CD, infra & configs
**Signals**
- Pipelines with manual approval gates or "run this by hand if it fails"
- Many near-identical config blocks (per environment, per service)
- Runbooks with diagnosis trees ("if X, check Y")
- Secrets or credentials being handled by hand. Flag the risk and never copy the values.

**Classify:** following a runbook with a human present → **skill**. Running checks, deciding, rolling back, or running on a schedule → **agent**.

**Example names:** `running-release-checklist`, `diagnosing-failed-deploys`

## Prompt libraries & AI chat logs
**Signals**
- The same prompt reused with small edits. This is the strongest skill signal of all.
- Repeated corrections ("no, use our format", "remember to…"): know-how missing from the prompt
- Long pasted context blocks repeated across chats, which belong in a skill's references/

**Classify:** almost always a **skill**. Capture the prompt, the corrections, and the pasted context.

## Calendars, decks & other files
- **Calendars (.ics, exports):** recurring events with prep work attached → a pre-meeting **skill**. Scheduling across people and tools → an **agent**.
- **Decks:** the same slide structure every period → a reporting **skill** that produces the deck.
- **PDF bundles or scans:** repeated extraction of the same fields → a **skill with a script**.

## Measuring frequency and effort

Scoring and the build/borderline/skip decision are in skill-threshold.md (criteria 4 and 5). How to find the evidence:
- **Frequency:** dates and timestamps, rows per period, messages per intent cluster, commits per pattern. If the file doesn't state a frequency, infer it and mark the score as inferred.
- **Effort:** number of steps, hand-filled columns per row, length of the procedure, corrections or back-and-forth in threads.
- Quote the evidence in the plan ("33 of 70 commits", "≈40 rows/week").

## False positives & disqualifiers
- **Repeated in the text, but not in practice:** a boilerplate header or signature isn't a task.
- **One-off projects:** a migration plan or launch checklist that runs once (unless it's a template for future launches).
- **Fully deterministic, no judgement:** prefer a formula, macro, or scheduled script over Claude.
- **Too variable:** every instance is unique, so there's no stable procedure to capture.
- **Already covered:** an existing skill or built-in capability does it. Mention it instead of proposing a duplicate.
- **Tiny overlaps:** don't split one workflow into several near-identical skills. Merge them.
