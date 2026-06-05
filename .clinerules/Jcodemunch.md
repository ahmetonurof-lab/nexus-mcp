## OUTPUT DISCIPLINE

- Complete the task. Do not embellish.
- When finished, reply ONLY: "done."
- No summaries, tables, analyses, or markdown formatting unless explicitly asked.
- Errors/blocks: ONE sentence max.
- The user will ask if they want more detail.

## CODE EXPLORATION TOOLS

- For code exploration: use jcodemunch-MCP tools exclusively.
- Never use: Grep, Glob, Read (for exploration), Bash, or PowerShell for navigating or searching code.
- Exception: `Read` is allowed only when you are about to edit a file — the harness requires a `Read` before `Edit`/`Write` succeeds.
- git commit --no-verify -m "mesaj"