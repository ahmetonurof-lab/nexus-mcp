## codebase-memory-mcp (PRIMARY) <!-- codebase-memory MCP -->

**⚠️ ZORUNLU KURAL: Her codebase exploration işleminde ÖNCE codebase-memory MCP tool'larını kullan.**

Bu bir tercih değil, zorunluluktur. Kural ihlali değildir.

### Workflow (kesin sıralama)
1. `search_graph` - **HER ZAMAN İLK.** Sembol/fonksiyon/dosya/ilişki bul.
2. `get_code_snippet` - Kodu oku.
3. `trace_path` veya `get_architecture` - Derinlemesine bağlam al.
4. Değişiklikleri bağlam üzerinden yap.

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

### FORBIDDEN (do NOT do this)
- Do NOT use `grep`, `find`, `glob`, or `bash` for code exploration when MCP tools are available
- Do NOT open files one by one to find your way around — use `search_graph` first
- Do NOT guess file paths — use `search_graph` or `get_architecture`
- If MCP returns 0 results, tell the user — do NOT fall back to manual search silently

### Fallback Sadece Bu Durumlarda
- MCP tool'u error/failure döndürdüğünde
- MCP 0 sonuç döndüğünde ve kullanıcı onayladığında
- Runtime log, build output, .env, Dockerfile gibi non-code dosyalarda

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
