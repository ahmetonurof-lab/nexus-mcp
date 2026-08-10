#!/usr/bin/env python3
"""Test snapshot filename sort order with digit-wise inversion."""


def _reverse_sort_key(ts_str: str) -> str:
    return "".join(str(9 - int(c)) if c.isdigit() else c for c in ts_str)


# Test timestamps from different symbols
test_cases = [
    ("DOGEUSDT", "2026-08-09_223308"),
    ("RENDERUSDT", "2026-08-09_224627"),
    ("APTUSDT", "2026-08-09_025322"),
    ("LINKUSDT", "2026-08-09_151545"),
    ("ONDOUSDT", "2026-08-09_013505"),
    ("ATOMUSDT", "2026-08-09_075213"),
]

# Generate filenames as the code would
filenames = []
for sym, ts in test_cases:
    sort_key = _reverse_sort_key(ts)
    filename = f"{sort_key}_{sym}_{ts}.html"
    filenames.append((filename, ts, sym))

# Sort alphabetically (as ls/VS Code Explorer would)
sorted_files = sorted(filenames, key=lambda x: x[0])

print("Alphabetical order (as shown in explorer):")
print("=" * 80)
for i, (fname, ts, sym) in enumerate(sorted_files, 1):
    print(f"{i:2}. {fname}")
    print(f"    Time: {ts} | Symbol: {sym}")

# Verify chronological order (newest first)
print("\nExpected newest-first chronological order:")
print("=" * 80)
sorted_by_time = sorted(filenames, key=lambda x: x[1], reverse=True)
for i, (fname, ts, sym) in enumerate(sorted_by_time, 1):
    print(f"{i:2}. {fname}")
    print(f"    Time: {ts} | Symbol: {sym}")

# Check if they match
print("\nVerification:")
print("=" * 80)
matches = all(
    sorted_files[i][1] == sorted_by_time[i][1] for i in range(len(sorted_files))
)
if matches:
    print("PASS: Alphabetical order matches reverse-chronological order!")
    print("  En yeni trade dosya listesinde EN ÜSTTE görünecek.")
else:
    print("FAIL: Order mismatch!")
    for i in range(len(sorted_files)):
        if sorted_files[i][1] != sorted_by_time[i][1]:
            print(
                f"  Position {i+1}: expected {sorted_by_time[i][1]}, got {sorted_files[i][1]}"
            )
