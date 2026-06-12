# ═══════════════════════════════════════════════════════════════
# GLOBAL RULES — jCodeMunch + Nexus MCP
# ═══════════════════════════════════════════════════════════════

## ── 1. STRICT CONTEXT MANAGEMENT ──
- Do NOT list the file structure.
- Do NOT read any files automatically upon startup.
- Metadata (environment details) must be ignored.
- Use `jcodemunch` via MCP for all file operations.
- Wait for explicit user instructions before taking ANY action.
- **Minimal yanıt**: Sadece isteneni söyle, detayı ancak sorulursa ver. "Özgeç" ağırlıklı konuş.

## ── 2. PATH SCOPING ──
### Start here
```
paths:
  - "src/**"
```
### Then narrow down
```
paths:
  - "src/features/auth/**"
```

## ── 3. jcodemunch MCP INTEGRATION ──

### Öncelik Kuralı
Kod okumak/aramak için ÖNCE jcodemunch araçlarını kullan (`search_symbols`, `get_file_outline`, `get_symbol_source`, `get_file_content`), sonra `read_file` veya `search_files` dene.

### Kullanım Sırası
1. `search_symbols` ile sembol ara (dosya okumaktan daha hafif)
2. `get_file_outline` ile dosyadaki tüm fonksiyon/sınıf imzalarını gör
3. `get_context_bundle` ile bir sembolün tüm bağlamını (import'lar + kaynak) tek çağrıda al
4. Sadece jcodemunch yetmezse `read_file` veya `search_files` kullan

### Auto-approve Edilenler
- `resolve_repo` → repo ID'sini çöz
- `register_edit` → dosya değişikliğinden sonra cache temizle

### İndexli Proje
- Repo: `ahmetonurof-lab/nexus-mcp`
- Dosya sayısı: 2000
- Sembol sayısı: 24730

## ── 4. jCodeMunch VS Code EXTENSION ──
`vscode-extension/` (local only — gitignored)

### Auto-reindex on Save
Dosya kaydedildiğinde `jcodemunch-mcp index-file <path>` otomatik çalıştırır.

### Risk Gutter
Açık dosyadaki fonksiyon/metot risk skorlarını gutter'da renkli noktalarla gösterir (🟡🟠🔴).

### Komutlar
- `jcodemunch.reindexFile` — aktif dosyayı manuel reindex eder
- `jcodemunch.refreshRiskGutter` — risk göstergelerini manuel yeniler
