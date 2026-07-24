## codebase-memory-mcp (PRIMARY) <!-- codebase-memory MCP -->

**MANDATORY: use codebase-memory tools FIRST for ALL codebase exploration.**
codebase-memory-mcp provides graph-based code analysis with symbol search, impact analysis, and session context.

### Workflow
1. `search_graph` - ALWAYS FIRST. Searches codebase graph for relevant symbols, files, and relationships.
2. `trace_path` or `get_architecture` - Get deeper context after initial search.
3. Make changes based on context.

### Available MCP tools
- `search_graph` - **OPENING MOVE**. Searches code graph for symbols, files, and relationships.
  Use this at the START of every task.
  Example: `search_graph({ "query": "fix JWT expiry in AuthService.validateToken" })`
- `trace_path` - Trace call/import chains between symbols.
  Example: `trace_path({ "from": "AuthService.validateToken", "to": "TokenRepository" })`
- `get_architecture` - Get high-level architecture overview of a module or directory.
- `get_symbol_detail` - Detailed symbol info (type, location, usages).
- `find_references` - Find all references to a symbol across the codebase.
- `get_file_summary` - Summary of a file's exports, imports, and dependencies.

### Search strategy
- `search_graph` for initial analysis → `get_symbol_detail` for specific patterns → `trace_path` for deep dives
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
