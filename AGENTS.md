# Copilot Instructions

## Tool Preferences
- Use jcodemunch MCP first: `search_symbols`, `get_file_outline`, `get_context_bundle` before `read_file`
- Fallback to `read_file` / `search_files` if jcodemunch insufficient
- Path scope: `sonnet/src/**` (primary). Read outside only if task requires it.
- **Don't overread**: Read minimum needed. No full-file dumps unless asked.

## Response Style
- **Minimal responses**: Say only what's asked. Details only when requested.
- **No context dumping**: Do NOT share summaries, code blocks, or full files unless explicitly asked.
- **Be concise**: If it's not requested, don't send it.

## Auto-approved
- `resolve_repo`, `register_edit`, `grep_search`

## Task Completion Protocol
When task is complete:
1. Update `memory-bank/` files
2. `git add -A && git commit`
3. **ASK before push**: "Push now?" → Wait for user confirmation
4. Push only if user says yes

## Honesty Protocol
- State what's missing if uncertain
- Ask before proceeding
- Never guess
