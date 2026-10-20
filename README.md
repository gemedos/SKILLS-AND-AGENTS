# SKILLS-AGENTS
Claude Project for Assited creation of Skills and Agents.  Modes: --skill , --agent , --EcoSys, --help

## HOW TO SETUP
1. Create a new Claude Project and paste the pointer instructions above into its instructions box.
2. Connect GitHub to Claude with your own GitHub account, then add the repo’s knowledge folder to the project’s knowledge.
3. Test it by starting a chat with --skill or --agent.
4. Resync whenever the owner announces an update.

```
At the start of every chat, read PROJECT_INSTRUCTIONS.md in project knowledge
and follow it exactly.

Routing rule (backup in case the file isn't loaded):
- --skill → Skill Builder mode
- --agent → Agent Builder mode
- --EcoSys (optional +file) → Framework Designer mode
- --help or no flag → Helper mode: explain the modes, don't build
```

## HOW TO COPY A FINISHED SKILL OR AGENT
To use a finished skill or agent, open skills-and-agents in the repo, download the folder or file you need, and install it in Claude or Claude Code.
