## jcodemunch context tools (PRIMARY) <!-- jcodemunch MCP -->

**MANDATORY: use jcodemunch tools FIRST for ALL codebase exploration.**
jcodemunch provides graph-based code analysis with symbol search, impact analysis, and session context.

### Workflow
1. `plan_turn` - ALWAYS FIRST. Analyzes query against codebase.
2. `search_text` or `assemble_task_context` - Deeper context after planning.
3. Make targeted changes.

### Available MCP tools
- `plan_turn` - **OPENING MOVE**. Query vs codebase → ranked symbols + files + confidence.
  Example: `plan_turn({ "repo": "nexus-mcp", "query": "..." })`
- `assemble_task_context` - Task-aware orchestrator (explore/debug/refactor/extend/audit/review).
- `search_text` - Full-text search (supports regex, context lines).
- `get_class_hierarchy` - Inheritance chain.
- `find_implementations` - Interface/abstract implementations.
- `check_delete_safe` - Preflight deletion check.
- `get_session_context` / `get_session_snapshot` - Session state.
- `digest` - Recent changes, hotspots, dead code overview.

### Search strategy
- `plan_turn` first → `search_text` for patterns → `assemble_task_context` for deep dives
- Runtime logs, build outputs: use normal shell tools
- Sub-agents get context passed from these tools

## Session End — Memory Bank Update & Commit <!-- mandatory -->

**Her iş bitiminde ZORUNLU:**

1. **Memory bank güncelle**: `memory-bank/` altındaki ilgili dosyaları güncelle (özellikle `activeContext.md`, `progress.md`, `chat.md`)
2. **Commit & Push**:
   ```bash
   git add -A
   git commit -m "feat: [yapılan işin kısa özeti]"
   git push
   ```
3. Commit mesajı kısa ve açıklayıcı olmalı, yapılan değişikliği özetlemeli

Bu adımlar agent kapatılmadan veya yeni task'a geçilmeden ÖNCE yapılmalıdır.
