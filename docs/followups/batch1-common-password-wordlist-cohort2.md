# Followup: Full common-password wordlist import (cohort-2 enhancement)

**Registered:** 2026-05-14  
**Source:** Batch 1 CP2 closure note (D-D)  
**Priority:** Cohort-2

## What was deferred

The `_COMMON_PASSWORDS` frozenset in `backend/app/schemas/user.py` contains 19 entries (top-20 minus `admin12345678`). The full Have I Been Pwned / NIST 800-63B recommended list contains millions of entries.

## What needs to be built

1. Download the HIBP top-100k password list (text file, ~1MB compressed)
2. Store it as `backend/app/data/common_passwords.txt.gz` (git-tracked, gzipped to keep repo small)
3. Replace the frozenset in `user.py` with a lazy-loaded `BloomFilter` or set loaded from the file at module import time
4. Update the validator to check membership against the full set
5. Keep the hardcoded 19-entry frozenset as a fast-path fallback if the file is missing

## Why deferred

- The top-19 list covers the passwords most commonly used in credential stuffing attacks against educational platforms
- Adding the full wordlist adds complexity (file loading, memory, startup time) that isn't justified before the first cohort
- `admin12345678` exclusion constraint makes the full list harder to manage — must document the exclusion list separately

## Notes

- DO NOT include `admin12345678` in the wordlist regardless of its real-world prevalence
- Bloom filter false-positive rate of 0.1% is acceptable (occasionally rejecting a valid password is better than missing a common one)
