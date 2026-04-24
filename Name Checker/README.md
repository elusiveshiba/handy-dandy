# Name Checker

Check if a project name is available on GitHub, npm, and PyPI.

## Usage

```bash
node "Name Checker/name-checker.mjs" <name> [name2] [name3] ...
```

## Example

```bash
node "Name Checker/name-checker.mjs" glint rune flicker zephyr
```

Output:

```
name-checker - Checking 4 names...

[1/4] glint done
[2/4] rune done
[3/4] flicker done
[4/4] zephyr done

═══════════════════════════════════════════════════════════
  RESULTS
═══════════════════════════════════════════════════════════

Name      GH Repos GH Stars   npm          PyPI
────────────────────────────────────────────────
glint     4        892        ✗ 1.2k/mo    ✗ taken
rune      2        156        ✗ 89/mo      ✗ taken
flicker   1        45         ✓ free       ✗ taken
zephyr    6        12.4k      ✗ 234/mo     ✗ taken
────────────────────────────────────────────────

Notable GitHub conflicts:
  zephyr: zephyrproject-rtos/zephyr (12.4k★)
    Primary Git Repository for the Zephyr Project
```

## Features

- Checks GitHub for repos with exact name matches
- Shows the count of exact-match GitHub repos and the total stars across those exact matches
- Checks npm registry availability and monthly downloads
- Checks PyPI availability
- Handles rate limits with automatic exponential backoff
- Shows progress as names are checked
- Prints a summary table without risk scoring

## Requirements

Node.js 18+ (uses native `fetch`)
