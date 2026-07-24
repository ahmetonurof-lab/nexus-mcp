## codebase-memory-mcp context tools (PRIMARY) <!-- codebase-memory MCP -->

**MANDATORY: use codebase-memory tools FIRST for ALL codebase exploration.**
codebase-memory-mcp provides graph-based code analysis with symbol search, impact analysis, and session context.

### Workflow
1. `search_graph` - ALWAYS FIRST. Searches codebase graph for relevant symbols, files, and relationships.
2. `trace_path` or `get_architecture` - Get deeper context after initial search.
3. Make targeted changes.

### Available MCP tools
- `search_graph` - **OPENING MOVE**. Searches code graph for symbols, files, and relationships.
  Example: `search_graph({ "query": "fix JWT expiry in AuthService.validateToken" })`
- `trace_path` - Trace call/import chains between symbols.
- `get_architecture` - High-level architecture overview of a module or directory.
- `get_symbol_detail` - Detailed symbol info (type, location, usages).
- `find_references` - Find all references to a symbol across the codebase.
- `get_file_summary` - Summary of a file's exports, imports, and dependencies.

### Search strategy
- `search_graph` for initial analysis → `get_symbol_detail` for specific patterns → `trace_path` for deep dives
- Runtime logs, build outputs: use normal shell tools
- Sub-agents get context passed from these tools

### FORBIDDEN (do NOT do this)
- Do NOT use `grep`, `find`, `glob`, or `bash` for code exploration when MCP tools are available
- Do NOT open files one by one to find your way around — use `search_graph` first
- Do NOT guess file paths — use `search_graph` or `get_architecture`
- If MCP returns 0 results, tell the user — do NOT fall back to manual search silently

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
