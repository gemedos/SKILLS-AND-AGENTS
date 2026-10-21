# Prompt vs skill vs agent

Pick the simplest option that works. Only add complexity when it clearly pays off.

## Plain prompt
Use when the task is short, a single step, and needs no special context. Mention it, don't build it.

## Skill
A folder of instructions (plus optional scripts and references) that Claude loads inside a chat when relevant. Choose a skill when:
- The task is a repeatable procedure with known steps
- It needs specific know-how: house rules, templates, formats, domain facts
- A human is present to give input and review results
- Deterministic parts can be covered by bundled scripts

Examples: drafting guest replies in house style, monthly occupancy report from a CSV, cleaning a bookings export.

## Agent
A configured assistant with its own system prompt, tools, and loop (for example a Claude Code subagent or an Agent SDK app). Choose an agent only when at least one of these applies:
- It must take many steps on its own and decide its next step from results
- It needs its own tools or MCP servers (email, calendar, CRM, repo, APIs)
- It should run unattended or on a schedule
- It benefits from a separate context window (heavy research, large codebases)

Examples: an inbox triage agent that reads, labels, and drafts replies; a deploy agent that runs checks and rolls back.

## Tie-breakers
- Not sure → skill. A skill can be promoted to an agent later.
- Several related skills that always run in sequence may make one agent that uses them. Say so in the plan rather than splitting them up.
