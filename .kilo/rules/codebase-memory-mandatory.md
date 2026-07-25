# Codebase Memory MCP — ZORUNLU KURAL

## Kural

**Her codebase exploration işleminde ÖNCE `search_graph` veya `get_architecture` kullan.**

Bu tercih değil, zorunluluktur. Kural ihlali değildir.

## Sıralama

1. `search_graph` — sembol/fonksiyon/dosya bul
2. `get_code_snippet` — kodu oku
3. `trace_path` — çağrışım zincirini izle
4. `get_architecture` — yüksek seviye yapı
5. `find_references` — referansları bul

**Eğer MCP 0 sonuç dönerse veya error verirse** → fallback olarak grep/glob/read kullan. Ama ÖNCE MCP dene.

## Yasak

- Dosya bulmak için `grep` kullanma (MCP varken)
- Kod okumak için `read` ile dosya açma (MCP varken)
- Çağrı zincirini bulmak için `grep -r` kullanma
- `find` veya `glob` ile sembol arama

## İzin

- String literal, error message, config değeri → grep OK
- Non-code dosyalar (Dockerfile, shell script, .env) → grep OK
- Runtime log, build output → grep OK
- Dosya içeriği okuma (MCP sonrası doğrulama) → read OK

## Prompt Tetikleme

Aşağıdaki kelimeleri duyduğunda MCP'yi otomatik ateşle:
- "bul", "bul", "find", "search", "nerede", "where"
- "bağlantı", "ilişki", "relation", "connection"
- "kim çağırıyor", "who calls", "trace"
- "akış", "flow", "pipeline", "chain"
- "mimari", "architecture", "yapı"
- Herhangi bir sembol adı (fonksiyon, class, modül)
