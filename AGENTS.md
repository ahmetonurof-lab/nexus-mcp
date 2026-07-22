## jcodemunch (PRIMARY) <!-- jcodemunch MCP -->

**MANDATORY: use jcodemunch tools FIRST for ALL codebase exploration.**
jcodemunch provides graph-based code analysis with symbol search, impact analysis, and session context.

### Workflow
1. `plan_turn` - ALWAYS FIRST. Analyzes query against codebase, returns confidence + recommended symbols/files.
2. `search_text` or `assemble_task_context` - Get deeper context after planning.
3. Make changes based on context.

### Available MCP tools
- `plan_turn` - **OPENING MOVE**. Analyzes query vs codebase, returns ranked symbols + files + confidence.
  Use this at the START of every task.
  Example: `plan_turn({ "repo": "nexus-mcp", "query": "fix JWT expiry in AuthService.validateToken" })`
- `assemble_task_context` - Task-aware orchestrator. Auto-classifies intent (explore/debug/refactor/extend/audit/review).
  Example: `assemble_task_context({ "repo": "nexus-mcp", "task": "...", "intent": "debug" })`
- `search_text` - Full-text search across indexed files (supports regex, context lines).
- `get_class_hierarchy` - Inheritance chain for a class.
- `find_implementations` - Find implementations of interface/abstract class.
- `check_delete_safe` - Preflight deletion safety check.
- `get_session_context` / `get_session_snapshot` - Session continuity.
- `audit_agent_config` - Audit config files for token waste.
- `digest` - Stand-up briefing: recent changes, hotspots, dead code.

### Search strategy
- `plan_turn` for initial analysis → `search_text` for specific patterns → `assemble_task_context` for deep dives
- For runtime logs, build output (dist/, .venv/, node_modules/) use normal shell tools
- Pass context from these tools to sub-agents rather than letting them search independently

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
