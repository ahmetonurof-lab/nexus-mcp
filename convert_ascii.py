#!/usr/bin/env python3
"""
Parse main.py using tokenize, replace non-ASCII inside STRING and COMMENT tokens.
Uses precise start/end positions from tokenize to avoid any string boundary issues.
"""

import ast
import io
import sys
import tokenize
from collections import Counter

# Turkish -> ASCII
ASCII_MAP = {
    "ı": "i",
    "ğ": "g",
    "ü": "u",
    "ş": "s",
    "ö": "o",
    "ç": "c",
    "İ": "I",
    "Ğ": "G",
    "Ü": "U",
    "Ş": "S",
    "Ö": "O",
    "Ç": "C",
    "â": "a",
    "î": "i",
    "û": "u",
    "ô": "o",
    "ê": "e",
    "Â": "A",
    "Î": "I",
    "Û": "U",
    "Ô": "O",
    "Ê": "E",
    # Latin-1 mojibake
    "Ã": "A",
    "¢": "c",
    "¬": "-",
    "¡": "!",
    "€": "E",
    "Š": "S",
    "Œ": "OE",
    "Ž": "Z",
    "š": "s",
    "œ": "oe",
    "ž": "z",
    "Ÿ": "Y",
    "À": "A",
    "Á": "A",
    "Ä": "A",
    "Å": "A",
    "Æ": "AE",
    "È": "E",
    "É": "E",
    "Ë": "E",
    "Ì": "I",
    "Í": "I",
    "Ï": "I",
    "Ð": "D",
    "Ñ": "N",
    "Ò": "O",
    "Ó": "O",
    "Õ": "O",
    "×": "x",
    "Ø": "O",
    "Ù": "U",
    "Ú": "U",
    "Ý": "Y",
    "Þ": "TH",
    "ß": "ss",
    "à": "a",
    "á": "a",
    "ä": "a",
    "å": "a",
    "æ": "ae",
    "è": "e",
    "é": "e",
    "ë": "e",
    "ì": "i",
    "í": "i",
    "ï": "i",
    "ð": "d",
    "ñ": "n",
    "ò": "o",
    "ó": "o",
    "õ": "o",
    "÷": "/",
    "ø": "o",
    "ù": "u",
    "ú": "u",
    "ý": "y",
    "þ": "th",
    "ÿ": "y",
    # Smart quotes -> safe alternatives (MUST NOT produce real Python quote marks!)
    # These are double-quote-like chars that would break Python string syntax
    "\u2018": "'",
    "\u2019": "'",
    "\u201a": ",",
    "\u201b": "'",
    "\u201c": "<<",
    "\u201d": ">>",
    "\u201e": ",,",
    "\u201f": ",,",
    # Dashes
    "\u2013": "-",
    "\u2014": "--",
    # Misc
    "\u2026": "...",
    "\u2022": "*",
    "\u2020": "+",
    "\u2021": "+",
    "\u2030": "%",
    "\u2039": "<",
    "\u203a": ">",
    "\u02c6": "^",
    "\u02dc": "~",
    "\u00a0": " ",
    "\u00ad": "-",
    "\u2122": "(TM)",
    "\u0192": "f",
    "±": "+/-",
    "²": "2",
    "³": "3",
    "µ": "u",
    "¶": "P",
    "·": ".",
    "¹": "1",
    "º": "o",
    "»": ">>",
    "¼": "1/4",
    "½": "1/2",
    "¾": "3/4",
    "¿": "?",
}

EMOJI_MAP = {
    0x2705: "[OK]",
    0x274C: "[X]",
    0x26A0: "[WARN]",
    0x26A1: "[BOLT]",
    0x1F534: "[RED]",
    0x1F7E2: "[GRN]",
    0x1F6A8: "[ALERT]",
    0x1F525: "[FIRE]",
    0x1F504: "[SYNC]",
    0x1F4A1: "[BULB]",
    0x1F680: "[ROCKET]",
    0x1F44D: "[THUMBUP]",
    0x1F44E: "[THUMBDN]",
    0x1F4C8: "[UP]",
    0x1F4C9: "[DN]",
    0x1F4CA: "[CHART]",
    0x1F511: "[KEY]",
    0x1F512: "[LOCK]",
    0x1F513: "[UNLOCK]",
    0x1F514: "[BELL]",
    0x1F515: "[NOBELL]",
    0x1F3AF: "[TARGET]",
    0x2B50: "[STAR]",
    0x1F31F: "[STAR]",
    0x1F4E2: "[ANNOUNCE]",
    0x1F4E3: "[MEGAPHONE]",
    0x1F38A: "[CONFETTI]",
    0x1F4A8: "[DASH]",
    0x1F4BB: "[LAPTOP]",
    0x1F4DE: "[PHONE]",
    0x1F4B0: "[MONEY]",
    0x1F3C6: "[TROPHY]",
    0x1F44F: "[CLAP]",
    0x1F64C: "[RAISE]",
    0x1F64F: "[FOLD]",
    0x1F448: "[LEFT]",
    0x1F449: "[RIGHT]",
    0x1F446: "[UP]",
    0x1F447: "[DOWN]",
    0x1F600: "[GRIN]",
    0x1F602: "[TEARS]",
    0x1F603: "[SMILE]",
    0x1F604: "[SMILE]",
    0x1F60A: "[BLUSH]",
    0x1F60E: "[COOL]",
    0x1F61E: "[SAD]",
    0x1F620: "[ANGRY]",
    0x1F621: "[RAGE]",
    0x1F622: "[CRY]",
    0x1F62D: "[SOB]",
    0x1F631: "[SCREAM]",
    0x1F632: "[SHOCK]",
    0x1F44A: "[FIST]",
    0x1F4A3: "[BOMB]",
    0x1F48E: "[GEM]",
    0x1F389: "[PARTY]",
}


def replace_char(c):
    cp = ord(c)
    if cp < 128:
        return c
    tag = EMOJI_MAP.get(cp)
    if tag:
        return tag
    if cp == 0xFE0F:
        return ""
    repl = ASCII_MAP.get(c)
    if repl:
        return repl
    return "?"


# Read source
with open("sonnet/src/main.py", encoding="utf-8") as f:
    source = f.read()

# Convert to list for mutable character-by-character access
source_chars = list(source)

# Track which positions we've modified
modified = set()

# Tokenize and find STRING and COMMENT token boundaries
tokens = list(tokenize.generate_tokens(io.StringIO(source).readline))

for tok in tokens:
    if tok.type != tokenize.ENDMARKER:
        start = tok.start
        end = tok.end

        # Convert to flat index
        # Line numbers are 1-indexed, columns 0-indexed
        start_lineno, start_col = start
        end_lineno, end_col = end

        if start_lineno == end_lineno:
            # Single line
            line_idx = start_lineno - 1
            # Calculate flat index
            # Sum of line lengths up to start_lineno-1
            prefix_len = sum(len(line) + 1 for line in source.split("\n")[:line_idx])
            start_idx = prefix_len + start_col
            end_idx = prefix_len + end_col

            for i in range(start_idx, end_idx):
                if i not in modified:
                    old_c = source_chars[i]
                    new_c = replace_char(old_c)
                    if new_c != old_c and ord(old_c) > 127:
                        source_chars[i] = new_c
                        modified.add(i)
        else:
            # Multi-line token (triple-quoted string or multi-line comment)
            lines = source.split("\n")
            base_idx = sum(len(line) + 1 for line in lines[: start_lineno - 1])

            for lineno in range(start_lineno, end_lineno + 1):
                line = lines[lineno - 1]
                if lineno == start_lineno:
                    s = start_col
                    e = len(line)
                elif lineno == end_lineno:
                    s = 0
                    e = end_col
                else:
                    s = 0
                    e = len(line)

                line_start = sum(len(lines[i]) + 1 for i in range(lineno - 1))
                for i in range(line_start + s, line_start + e):
                    if i not in modified:
                        old_c = source_chars[i]
                        new_c = replace_char(old_c)
                        if new_c != old_c and ord(old_c) > 127:
                            source_chars[i] = new_c
                            modified.add(i)

new_source = "".join(source_chars)

# AST validation
try:
    ast.parse(new_source)
    print("AST validation: OK!")
except SyntaxError as e:
    print(f"AST FAILED at line {e.lineno}: {e.msg}")
    if e.lineno:
        lines = new_source.split("\n")
        if e.lineno <= len(lines):
            start = max(0, e.lineno - 3)
            end = min(len(lines), e.lineno + 2)
            for i in range(start, end):
                marker = ">>>" if i + 1 == e.lineno else "   "
                print(f"{marker} {i + 1}: {lines[i][:200]}")
    sys.exit(1)

# Write
with open("sonnet/src/main.py", "w", encoding="utf-8") as f:
    f.write(new_source)

remaining = sum(1 for c in new_source if ord(c) > 127)
print(f"Chars replaced: {len(modified)}")
print(f"Remaining non-ASCII: {remaining}")
if remaining:
    chars = Counter(c for c in new_source if ord(c) > 127)
    print("Remaining chars:")
    for c, count in chars.most_common(10):
        print(f"  U+{ord(c):04X} ({c!r}): {count}")
else:
    print("SUCCESS: All non-ASCII removed!")
