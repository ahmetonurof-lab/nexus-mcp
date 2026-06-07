#!/usr/bin/env python3
"""
update_index.py — Nexus MCP Code Index Güncelleyici
====================================================
Her git commit öncesi otomatik çalışır (pre-commit hook).
sonnet/src/ altındaki tüm .py dosyalarını AST ile parse eder,
.claude_index/code_index.json dosyasını günceller.

Kullanım:
  python update_index.py              # Manuel çalıştır
  python update_index.py --dry-run    # Değişiklik yapmadan göster
"""

import ast
import json
import sys
import time
from pathlib import Path

# ── Repo kökünü bul ──────────────────────────────────────────────────
SCRIPT_DIR = Path(__file__).parent.resolve()
REPO_ROOT = SCRIPT_DIR  # script repo kökünde
SRC_DIR = REPO_ROOT / "sonnet" / "src"
OUTPUT_DIR = REPO_ROOT / ".claude_index"
OUTPUT_FILE = OUTPUT_DIR / "code_index.json"

DRY_RUN = "--dry-run" in sys.argv


def parse_file(filepath: Path) -> dict:
    """Bir .py dosyasını AST ile parse edip class/fonksiyon map'i çıkar."""
    result = {"description": "", "classes": {}, "module_level_functions": {}}

    try:
        source = filepath.read_text(encoding="utf-8")
        tree = ast.parse(source)
    except Exception as e:
        result["parse_error"] = str(e)
        return result

    # Dosya docstring'i
    if ast.get_docstring(tree):
        result["description"] = ast.get_docstring(tree).split("\n")[0]

    for node in ast.walk(tree):
        # ── Sınıflar ──
        if isinstance(node, ast.ClassDef):
            class_info = {"line": node.lineno, "methods": {}}
            # Sınıf docstring
            if ast.get_docstring(node):
                class_info["description"] = ast.get_docstring(node).split("\n")[0]

            for item in node.body:
                if isinstance(item, ast.FunctionDef | ast.AsyncFunctionDef):
                    # Çağrılan fonksiyonları çıkar
                    calls = []
                    for child in ast.walk(item):
                        if isinstance(child, ast.Call):
                            if isinstance(child.func, ast.Attribute):
                                call_str = f"{_get_attr_chain(child.func)}"
                                if call_str and len(call_str) < 60:
                                    calls.append(call_str)
                            elif isinstance(child.func, ast.Name):
                                calls.append(child.func.id)

                    # Deduplicate, ilk 10 çağrı
                    seen = set()
                    unique_calls = []
                    for c in calls:
                        if c not in seen:
                            seen.add(c)
                            unique_calls.append(c)

                    class_info["methods"][item.name] = {
                        "line": item.lineno,
                        "async": isinstance(item, ast.AsyncFunctionDef),
                        "calls": unique_calls[:12],
                    }

            result["classes"][node.name] = class_info

        # ── Modül seviyesi fonksiyonlar ──
        elif isinstance(node, ast.FunctionDef | ast.AsyncFunctionDef):
            # Sadece doğrudan modül düzeyindeki fonksiyonlar (iç içe değil)
            parent_classes = [n for n in ast.walk(tree) if isinstance(n, ast.ClassDef) and node in ast.walk(n)]
            if not parent_classes:
                calls = []
                for child in ast.walk(node):
                    if isinstance(child, ast.Call):
                        if isinstance(child.func, ast.Name):
                            calls.append(child.func.id)
                seen = set()
                unique_calls = [c for c in calls if c not in seen and not seen.add(c)]
                result["module_level_functions"][node.name] = {
                    "line": node.lineno,
                    "async": isinstance(node, ast.AsyncFunctionDef),
                    "calls": unique_calls[:10],
                }

    return result


def _get_attr_chain(node) -> str:
    """ast.Attribute zincirini string'e çevirir (örn: self._api_semaphore)."""
    parts = []
    while isinstance(node, ast.Attribute):
        parts.append(node.attr)
        node = node.value
    if isinstance(node, ast.Name):
        parts.append(node.id)
    return ".".join(reversed(parts))


def build_index() -> dict:
    """Tüm src dosyalarını tara ve index oluştur."""
    index = {
        "meta": {
            "repo": "ahmetonurof-lab/nexus-mcp",
            "branch": "main",
            "generated": time.strftime("%Y-%m-%d %H:%M:%S"),
            "src_dir": str(SRC_DIR.relative_to(REPO_ROOT)),
            "description": "Nexus V2 Binance Futures Trading Bot — auto-generated code index",
        },
        "files": {},
    }

    if not SRC_DIR.exists():
        print(f"⚠️  SRC_DIR bulunamadı: {SRC_DIR}")
        return index

    py_files = sorted(SRC_DIR.glob("*.py"))
    print(f"📂 {len(py_files)} Python dosyası bulundu: {SRC_DIR}")

    for filepath in py_files:
        rel_path = str(filepath.relative_to(REPO_ROOT))
        print(f"   ⚙️  parse ediliyor: {rel_path}")
        file_data = parse_file(filepath)

        # Sınıf/fonksiyon sayısı
        n_classes = len(file_data.get("classes", {}))
        n_funcs = len(file_data.get("module_level_functions", {}))
        n_methods = sum(len(c.get("methods", {})) for c in file_data.get("classes", {}).values())
        print(f"      → {n_classes} class, {n_methods} method, {n_funcs} fonksiyon")

        index["files"][rel_path] = file_data

    return index


def main():
    print("🔄 Nexus Code Index güncelleniyor...\n")

    index = build_index()

    total_files = len(index["files"])
    total_classes = sum(len(f.get("classes", {})) for f in index["files"].values())
    total_methods = sum(
        len(cls.get("methods", {})) for f in index["files"].values() for cls in f.get("classes", {}).values()
    )

    print("\n📊 Özet:")
    print(f"   Dosya: {total_files}")
    print(f"   Sınıf: {total_classes}")
    print(f"   Method/Fonksiyon: {total_methods}")

    if DRY_RUN:
        print("\n🔍 DRY RUN — dosya yazılmadı")
        print(json.dumps(index["meta"], indent=2, ensure_ascii=False))
        return

    OUTPUT_DIR.mkdir(exist_ok=True)
    OUTPUT_FILE.write_text(json.dumps(index, indent=2, ensure_ascii=False), encoding="utf-8")
    print(f"\n✅ {OUTPUT_FILE} güncellendi ({OUTPUT_FILE.stat().st_size // 1024} KB)")


if __name__ == "__main__":
    main()
