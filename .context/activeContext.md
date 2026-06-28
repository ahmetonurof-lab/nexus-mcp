# Active Context

## Current Work
- Fixed marker rendering in chart_template.html (Lightweight Charts snapshot system)
- Root cause: Multiple markers sharing same time+position combo (Lightweight Charts only shows last marker per position per bar)

## Changes Made
- `sniper/src/snapshot/chart_template.html`:
  - Initial SL marker moved from `belowBar`/`aboveBar` to `inBar` position to avoid conflict with entry marker
  - Trail step markers detect position conflict with exit marker on same bar and fall back to `inBar`
  - Added bounds check for `D.exitBar` before accessing `C[D.exitBar].time` to prevent crash
  - jcodemunch optimization: removed comments and blank lines (69→54 lines)

## Verification
- No duplicate time+position combos across all 24 markers
- Long and short trade screenshots render successfully
- Playwright headless Chromium captures all markers

## Open Questions
- None
