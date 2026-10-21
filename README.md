# SKILLS-AGENTS
Claude Project for Assited creation of Skills and Agents.  Modes: --skill , --agent , --EcoSys, --help

## HOW TO SETUP
### GITHUB CONNECTOR IS AVAILABLE
1. Create a new Claude Project and paste the pointer instructions underneath into its instructions box.
2. Connect GitHub to Claude with your own GitHub account, then add the repo’s knowledge folder to the project’s knowledge.
3. Test it by starting a chat with --skill or --agent.
4. Resync whenever the owner announces an update.

### GITHUB CONNECTOR IS NOT AVAILABLE
1. Go to a folder Claude can acces to in your local machine
2. Open the cmd on that directory and run ``` git clone https://github.com/gemedos/SKILLS-AND-AGENTS.git ```
3. Create a new Claude Project and paste the pointer instructions underneath into its instructions box.
4. Add the repo’s knowledge folder as the project’s Context .
5. Test it by starting a chat with --skill or --agent.
6. Resync whenever the owner announces an update.

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

## SAVING A COPY OF SKILLS
If you want to save the skills and agents created to the local repo for safekeeping or to push them to the remote repo after.
1. paste this claude in the claude project instructions box beneath the pointer instruction
2. Add your local repo's "skills-and-agents" folder to the editable folder in your Claude project.

```
## Saving finished builds
Save a copy of every finished skill or agent to the local repo folder:
[FULL PATH TO]/skills-and-agents/

- Skills go in skills/<skill-name>/ as the complete skill folder: SKILL.md plus any
  scripts/, references/, and assets/.
- Agents go in agents/<agent-name>/ with all files for that agent (for a Claude Code
  subagent, the .md definition file).
- Use kebab-case names that match the name in the skill's or agent's frontmatter.
- Only save after the user approves the final version. Never save drafts.
- If a folder with that name already exists, ask whether to overwrite it or save it
  as a new version (e.g. <name>-v2) before writing anything.
- After saving, list the exact file paths that were written.
- If the folder can't be reached, say so and provide the files for download instead.
- Don't run git commands or push anything. The user commits and pushes.
```
