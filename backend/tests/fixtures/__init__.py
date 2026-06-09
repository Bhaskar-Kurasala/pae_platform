"""Reusable test fixtures shared across pytest test files and standalone
real-LLM verification scripts.

D15 introduced the role-state schema; CP3 onward needs seeded students
at multiple progression states (python_developer fresh, mid-progression
data_analyst / data_scientist, etc.). Hosting the seed helpers here so
test files AND scripts/d15_cp3_*.py can import them without duplicating
the SQL.
"""
