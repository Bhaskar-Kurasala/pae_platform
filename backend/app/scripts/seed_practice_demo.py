"""Seed 5 starter exercises + 1 capstone for the /practice screen.

Idempotent. Run via:
    docker compose exec backend uv run python -m app.scripts.seed_practice_demo

Each exercise carries:
  - real problem statement
  - starter code (the student edits this)
  - test_cases (input/expected pairs the platform's grader checks)
  - rubric (dimensions admin uses for review)
  - difficulty, points, pass_score

The capstone is a multi-step "build a CLI todo manager" project with a
markdown brief in description (no test_cases — capstones go through
human review via the existing senior_review path).

All exercises attach to lessons in the existing seed_learn_demo course
("Learn Demo: Python Foundations") so the seed is self-contained.
"""

from __future__ import annotations

import asyncio
import uuid

import structlog
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import AsyncSessionLocal
from app.models.course import Course
from app.models.exercise import Exercise
from app.models.lesson import Lesson

log = structlog.get_logger()

DEMO_COURSE_SLUG = "learn-demo-python-foundations"


# --------------------------------------------------------------------- #
# Problem definitions (the actual content)                              #
# --------------------------------------------------------------------- #


EX_FIZZBUZZ = {
    "title": "FizzBuzz",
    "difficulty": "easy",
    "points": 50,
    "pass_score": 80,
    "description": (
        "Write a function `fizzbuzz(n)` that returns a list of strings "
        "from 1 to n inclusive, where:\n\n"
        "- multiples of 3 → \"Fizz\"\n"
        "- multiples of 5 → \"Buzz\"\n"
        "- multiples of both → \"FizzBuzz\"\n"
        "- otherwise → the number as a string\n\n"
        "Example: `fizzbuzz(5)` → `['1', '2', 'Fizz', '4', 'Buzz']`."
    ),
    "starter_code": (
        "def fizzbuzz(n: int) -> list[str]:\n"
        "    out: list[str] = []\n"
        "    for i in range(1, n + 1):\n"
        "        # TODO: append the right string for i\n"
        "        out.append(str(i))\n"
        "    return out\n\n\n"
        "if __name__ == '__main__':\n"
        "    print(fizzbuzz(15))\n"
    ),
    "solution_code": (
        "def fizzbuzz(n: int) -> list[str]:\n"
        "    out: list[str] = []\n"
        "    for i in range(1, n + 1):\n"
        "        if i % 15 == 0:\n"
        "            out.append('FizzBuzz')\n"
        "        elif i % 3 == 0:\n"
        "            out.append('Fizz')\n"
        "        elif i % 5 == 0:\n"
        "            out.append('Buzz')\n"
        "        else:\n"
        "            out.append(str(i))\n"
        "    return out\n"
    ),
    "test_cases": {
        "cases": [
            {"args": [1], "expected": ["1"]},
            {"args": [3], "expected": ["1", "2", "Fizz"]},
            {"args": [5], "expected": ["1", "2", "Fizz", "4", "Buzz"]},
            {
                "args": [15],
                "expected": [
                    "1", "2", "Fizz", "4", "Buzz", "Fizz", "7", "8",
                    "Fizz", "Buzz", "11", "Fizz", "13", "14", "FizzBuzz",
                ],
            },
        ]
    },
    "rubric": {
        "dimensions": [
            {"name": "Correctness", "weight": 60},
            {"name": "Readability", "weight": 20},
            {"name": "Edge cases", "weight": 20},
        ]
    },
    "is_capstone": False,
}


EX_TWO_SUM = {
    "title": "Two Sum",
    "difficulty": "easy",
    "points": 75,
    "pass_score": 80,
    "description": (
        "Given an array of integers `nums` and an integer `target`, "
        "return indices of the two numbers that add up to target.\n\n"
        "Each input has exactly one solution, you may not use the same "
        "element twice. Return the indices in ascending order.\n\n"
        "Example: `two_sum([2,7,11,15], 9)` → `[0, 1]`."
    ),
    "starter_code": (
        "def two_sum(nums: list[int], target: int) -> list[int]:\n"
        "    # TODO: return the two indices that sum to target\n"
        "    return []\n\n\n"
        "if __name__ == '__main__':\n"
        "    print(two_sum([2, 7, 11, 15], 9))\n"
    ),
    "solution_code": (
        "def two_sum(nums: list[int], target: int) -> list[int]:\n"
        "    seen: dict[int, int] = {}\n"
        "    for i, n in enumerate(nums):\n"
        "        comp = target - n\n"
        "        if comp in seen:\n"
        "            return sorted([seen[comp], i])\n"
        "        seen[n] = i\n"
        "    return []\n"
    ),
    "test_cases": {
        "cases": [
            {"args": [[2, 7, 11, 15], 9], "expected": [0, 1]},
            {"args": [[3, 2, 4], 6], "expected": [1, 2]},
            {"args": [[3, 3], 6], "expected": [0, 1]},
        ]
    },
    "rubric": {
        "dimensions": [
            {"name": "Correctness", "weight": 50},
            {"name": "Time complexity (O(n) preferred)", "weight": 30},
            {"name": "Code clarity", "weight": 20},
        ]
    },
    "is_capstone": False,
}


EX_GROUP_BY_KEY = {
    "title": "Group records by key",
    "difficulty": "medium",
    "points": 100,
    "pass_score": 75,
    "description": (
        "Write `group_by(records, key)` that takes a list of dicts and a "
        "string key, and returns a dict mapping each distinct value of "
        "`record[key]` to the list of records sharing that value. Order "
        "within each group must preserve the input order.\n\n"
        "Example: `group_by([{'a':1,'b':2},{'a':1,'b':3}], 'a')` → "
        "`{1: [{'a':1,'b':2},{'a':1,'b':3}]}`."
    ),
    "starter_code": (
        "def group_by(records: list[dict], key: str) -> dict:\n"
        "    # TODO: bucket records by record[key]\n"
        "    return {}\n\n\n"
        "if __name__ == '__main__':\n"
        "    rows = [{'team': 'red', 'pts': 10}, {'team': 'blue', 'pts': 8},\n"
        "            {'team': 'red', 'pts': 7}]\n"
        "    print(group_by(rows, 'team'))\n"
    ),
    "solution_code": (
        "def group_by(records: list[dict], key: str) -> dict:\n"
        "    out: dict = {}\n"
        "    for r in records:\n"
        "        out.setdefault(r[key], []).append(r)\n"
        "    return out\n"
    ),
    "test_cases": {
        "cases": [
            {
                "args": [[{"a": 1, "b": 2}, {"a": 1, "b": 3}], "a"],
                "expected": {1: [{"a": 1, "b": 2}, {"a": 1, "b": 3}]},
            },
            {"args": [[], "k"], "expected": {}},
            {
                "args": [[{"team": "x", "n": 1}, {"team": "y", "n": 2}], "team"],
                "expected": {"x": [{"team": "x", "n": 1}], "y": [{"team": "y", "n": 2}]},
            },
        ]
    },
    "rubric": {
        "dimensions": [
            {"name": "Correctness", "weight": 60},
            {"name": "Use of dict.setdefault or defaultdict", "weight": 20},
            {"name": "Handles empty input", "weight": 20},
        ]
    },
    "is_capstone": False,
}


EX_FLATTEN_NESTED = {
    "title": "Flatten nested list",
    "difficulty": "medium",
    "points": 100,
    "pass_score": 75,
    "description": (
        "Implement `flatten(items)` that returns a flat list of every "
        "non-list value found at any nesting depth. The input may "
        "contain integers, strings, and arbitrarily-nested lists.\n\n"
        "Example: `flatten([1, [2, [3, 4]], 5])` → `[1, 2, 3, 4, 5]`."
    ),
    "starter_code": (
        "def flatten(items: list) -> list:\n"
        "    # TODO: walk every element; recurse into lists\n"
        "    return []\n\n\n"
        "if __name__ == '__main__':\n"
        "    print(flatten([1, [2, [3, [4]]], 5, [], [[6]]]))\n"
    ),
    "solution_code": (
        "def flatten(items: list) -> list:\n"
        "    out: list = []\n"
        "    for x in items:\n"
        "        if isinstance(x, list):\n"
        "            out.extend(flatten(x))\n"
        "        else:\n"
        "            out.append(x)\n"
        "    return out\n"
    ),
    "test_cases": {
        "cases": [
            {"args": [[]], "expected": []},
            {"args": [[1, 2, 3]], "expected": [1, 2, 3]},
            {"args": [[1, [2, [3, 4]], 5]], "expected": [1, 2, 3, 4, 5]},
            {"args": [[[[1]], [[2, [3]]]]], "expected": [1, 2, 3]},
        ]
    },
    "rubric": {
        "dimensions": [
            {"name": "Correctness on deep nesting", "weight": 50},
            {"name": "Handles empty + mixed types", "weight": 30},
            {"name": "Recursive vs iterative tradeoff explained", "weight": 20},
        ]
    },
    "is_capstone": False,
}


EX_PARSE_LOG = {
    "title": "Parse server log lines",
    "difficulty": "hard",
    "points": 150,
    "pass_score": 70,
    "description": (
        "Implement `parse_log(line)` that takes a single Apache common-log "
        "format line and returns a dict with keys: `ip`, `method`, "
        "`path`, `status`, `bytes`. Return `None` for malformed lines.\n\n"
        "Example input:\n"
        "`'192.168.1.1 - - [10/Oct/2024:13:55:36 +0000] \"GET /home HTTP/1.1\" 200 1234'`\n\n"
        "Should return:\n"
        "`{'ip': '192.168.1.1', 'method': 'GET', 'path': '/home', "
        "'status': 200, 'bytes': 1234}`"
    ),
    "starter_code": (
        "import re\n\n\n"
        "def parse_log(line: str) -> dict | None:\n"
        "    # TODO: parse the common-log format\n"
        "    return None\n\n\n"
        "if __name__ == '__main__':\n"
        "    sample = '127.0.0.1 - - [01/Jan/2025:10:00:00 +0000] \"POST /api HTTP/1.1\" 201 42'\n"
        "    print(parse_log(sample))\n"
    ),
    "solution_code": (
        "import re\n\n"
        "_PATTERN = re.compile(\n"
        "    r'^(?P<ip>\\S+) \\S+ \\S+ \\[[^\\]]+\\] '\n"
        "    r'\"(?P<method>[A-Z]+) (?P<path>\\S+) HTTP/[\\d.]+\" '\n"
        "    r'(?P<status>\\d+) (?P<bytes>\\d+)'\n"
        ")\n\n\n"
        "def parse_log(line: str) -> dict | None:\n"
        "    m = _PATTERN.match(line)\n"
        "    if m is None:\n"
        "        return None\n"
        "    return {\n"
        "        'ip': m.group('ip'),\n"
        "        'method': m.group('method'),\n"
        "        'path': m.group('path'),\n"
        "        'status': int(m.group('status')),\n"
        "        'bytes': int(m.group('bytes')),\n"
        "    }\n"
    ),
    "test_cases": {
        "cases": [
            {
                "args": [
                    '192.168.1.1 - - [10/Oct/2024:13:55:36 +0000] '
                    '"GET /home HTTP/1.1" 200 1234'
                ],
                "expected": {
                    "ip": "192.168.1.1",
                    "method": "GET",
                    "path": "/home",
                    "status": 200,
                    "bytes": 1234,
                },
            },
            {"args": ["this is not a log line"], "expected": None},
            {
                "args": [
                    '10.0.0.1 - alice [01/Jan/2025:00:00:00 +0000] '
                    '"POST /api/v1/users HTTP/1.1" 201 78'
                ],
                "expected": {
                    "ip": "10.0.0.1",
                    "method": "POST",
                    "path": "/api/v1/users",
                    "status": 201,
                    "bytes": 78,
                },
            },
        ]
    },
    "rubric": {
        "dimensions": [
            {"name": "Correct regex / parser", "weight": 50},
            {"name": "Returns None for malformed input", "weight": 25},
            {"name": "Type-correct status / bytes (int, not str)", "weight": 25},
        ]
    },
    "is_capstone": False,
}


CAPSTONE_TODO_CLI = {
    "title": "Capstone — CLI Todo Manager",
    "difficulty": "hard",
    "points": 500,
    "pass_score": 70,
    "description": (
        "## Capstone: Build a CLI todo manager\n\n"
        "Build a small command-line todo manager that persists tasks to a "
        "JSON file and supports the four commands below. The grader is a "
        "human (admin / senior reviewer) — there are no automated test "
        "cases on this one. Submit your code through /practice; admin "
        "will review and score against the rubric below.\n\n"
        "### Required commands\n\n"
        "- `add <text>` — appends a new task (auto-generated id, status='open')\n"
        "- `list` — prints all tasks; format: `<id> [<status>] <text>`\n"
        "- `done <id>` — marks the task complete\n"
        "- `rm <id>` — deletes the task\n\n"
        "### Constraints\n\n"
        "- Persist to `tasks.json` in the working directory\n"
        "- Survive restart: re-reading on start must show prior tasks\n"
        "- Handle missing/corrupt file gracefully\n"
        "- Use only the standard library\n\n"
        "### Stretch goals (optional, +bonus on rubric)\n\n"
        "- `--filter open|done` flag on `list`\n"
        "- Color output via ANSI codes\n"
        "- `--due YYYY-MM-DD` on `add`, sortable on `list`\n\n"
        "### Submission\n\n"
        "Paste the entire `todo.py` file into the editor. Run it locally "
        "to verify before submitting."
    ),
    "starter_code": (
        "\"\"\"todo.py — your CLI todo manager.\n\n"
        "Usage:\n"
        "    python todo.py add \"buy milk\"\n"
        "    python todo.py list\n"
        "    python todo.py done 1\n"
        "    python todo.py rm 1\n"
        "\"\"\"\n"
        "from __future__ import annotations\n\n"
        "import json\n"
        "import sys\n"
        "from pathlib import Path\n\n"
        "STORE = Path('tasks.json')\n\n\n"
        "def load() -> list[dict]:\n"
        "    # TODO: read STORE if it exists, return [] otherwise\n"
        "    return []\n\n\n"
        "def save(tasks: list[dict]) -> None:\n"
        "    # TODO: persist to STORE\n"
        "    pass\n\n\n"
        "def cmd_add(args: list[str]) -> int:\n"
        "    # TODO: append a task and save\n"
        "    return 0\n\n\n"
        "def cmd_list(args: list[str]) -> int:\n"
        "    # TODO: print every task\n"
        "    return 0\n\n\n"
        "def cmd_done(args: list[str]) -> int:\n"
        "    # TODO: mark task with id as done\n"
        "    return 0\n\n\n"
        "def cmd_rm(args: list[str]) -> int:\n"
        "    # TODO: delete task with id\n"
        "    return 0\n\n\n"
        "def main(argv: list[str]) -> int:\n"
        "    if len(argv) < 2:\n"
        "        print('usage: todo.py {add|list|done|rm} ...', file=sys.stderr)\n"
        "        return 2\n"
        "    handlers = {\n"
        "        'add': cmd_add, 'list': cmd_list,\n"
        "        'done': cmd_done, 'rm': cmd_rm,\n"
        "    }\n"
        "    cmd = argv[1]\n"
        "    if cmd not in handlers:\n"
        "        print(f'unknown command: {cmd}', file=sys.stderr)\n"
        "        return 2\n"
        "    return handlers[cmd](argv[2:])\n\n\n"
        "if __name__ == '__main__':\n"
        "    raise SystemExit(main(sys.argv))\n"
    ),
    "solution_code": None,  # admin doesn't reveal a solution for capstones
    "test_cases": None,  # human-graded
    "rubric": {
        "dimensions": [
            {"name": "All four commands work end-to-end", "weight": 30},
            {"name": "Persistence (survives restart)", "weight": 20},
            {"name": "Handles missing/corrupt JSON gracefully", "weight": 15},
            {"name": "Code organization + naming", "weight": 15},
            {"name": "Error messages are useful (non-zero exit codes, stderr)", "weight": 10},
            {"name": "Stretch goals attempted", "weight": 10},
        ],
        "human_review": True,
    },
    "is_capstone": True,
}


ALL_EXERCISES = [
    EX_FIZZBUZZ, EX_TWO_SUM, EX_GROUP_BY_KEY, EX_FLATTEN_NESTED, EX_PARSE_LOG,
    CAPSTONE_TODO_CLI,
]


# --------------------------------------------------------------------- #
# Helpers                                                               #
# --------------------------------------------------------------------- #


async def _ensure_exercise(
    db: AsyncSession,
    *,
    lesson_id: uuid.UUID,
    spec: dict,
    order: int,
) -> Exercise:
    """Find-or-create by (lesson_id, title)."""
    existing = (
        await db.execute(
            select(Exercise).where(
                Exercise.lesson_id == lesson_id,
                Exercise.title == spec["title"],
                Exercise.is_deleted.is_(False),
            )
        )
    ).scalar_one_or_none()
    if existing is not None:
        # Refresh content in place so re-running the seed picks up edits.
        existing.description = spec["description"]
        existing.starter_code = spec["starter_code"]
        existing.solution_code = spec.get("solution_code")
        existing.test_cases = spec.get("test_cases")
        existing.rubric = spec.get("rubric")
        existing.difficulty = spec["difficulty"]
        existing.points = spec["points"]
        existing.pass_score = spec["pass_score"]
        existing.is_capstone = spec["is_capstone"]
        existing.order = order
        await db.flush()
        return existing
    ex = Exercise(
        lesson_id=lesson_id,
        title=spec["title"],
        description=spec["description"],
        exercise_type="coding",
        difficulty=spec["difficulty"],
        starter_code=spec["starter_code"],
        solution_code=spec.get("solution_code"),
        test_cases=spec.get("test_cases"),
        rubric=spec.get("rubric"),
        points=spec["points"],
        pass_score=spec["pass_score"],
        is_capstone=spec["is_capstone"],
        order=order,
    )
    db.add(ex)
    await db.flush()
    return ex


async def main() -> None:
    async with AsyncSessionLocal() as db:
        course = (
            await db.execute(
                select(Course).where(Course.slug == DEMO_COURSE_SLUG)
            )
        ).scalar_one_or_none()
        if course is None:
            raise SystemExit(
                f"Course slug {DEMO_COURSE_SLUG!r} not found — run "
                "seed_learn_demo first."
            )

        lessons = list(
            (
                await db.execute(
                    select(Lesson)
                    .where(
                        Lesson.course_id == course.id,
                        Lesson.is_published.is_(True),
                    )
                    .order_by(Lesson.order.asc())
                )
            ).scalars().all()
        )
        if not lessons:
            raise SystemExit(
                "Demo course has no lessons — run seed_learn_demo first."
            )

        # Spread the 5 exercises across the available lessons; the
        # capstone goes on the last lesson.
        regular = [s for s in ALL_EXERCISES if not s["is_capstone"]]
        capstone = next(s for s in ALL_EXERCISES if s["is_capstone"])

        created: list[Exercise] = []
        for i, spec in enumerate(regular):
            target_lesson = lessons[i % len(lessons)]
            ex = await _ensure_exercise(
                db, lesson_id=target_lesson.id, spec=spec, order=i
            )
            created.append(ex)

        cap = await _ensure_exercise(
            db, lesson_id=lessons[-1].id, spec=capstone, order=len(regular),
        )
        created.append(cap)

        await db.commit()

        for ex in created:
            log.info(
                "seed_practice.exercise",
                id=str(ex.id),
                title=ex.title,
                difficulty=ex.difficulty,
                is_capstone=ex.is_capstone,
            )
        print(f"Seeded {len(created)} exercises (incl. 1 capstone).")
        print("Visit /practice as the demo user to see them.")


if __name__ == "__main__":
    asyncio.run(main())
