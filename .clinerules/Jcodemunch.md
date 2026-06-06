# jcodemunch Integration

## Öncelik Kuralı
Kod okumak/aramak için ÖNCE jcodemunch araçlarını kullan (`search_symbols`, `get_file_outline`, `get_symbol_source`, `get_file_content`), sonra `read_file` veya `search_files` dene.

## Kullanım Sırası
1. `search_symbols` ile sembol ara (dosya okumaktan daha hafif)
2. `get_file_outline` ile dosyadaki tüm fonksiyon/sınıf imzalarını gör
3. `get_context_bundle` ile bir sembolün tüm bağlamını (import'lar + kaynak) tek çağrıda al
4. Sadece jcodemunch yetmezse `read_file` veya `search_files` kullan

## Auto-approve Edilenler
- `resolve_repo` → repo ID'sini çöz
- `register_edit` → dosya değişikliğinden sonra cache temizle

## İndexli Proje
- Repo: `ahmetonurof-lab/nexus-mcp`
- Dosya sayısı: 2000
- Sembol sayısı: 24730