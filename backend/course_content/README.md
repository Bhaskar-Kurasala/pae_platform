# Course Content

Source of truth for course materials. The DB indexes this; it does not store
notebook contents.

## Layout

```
course_content/
  {course-slug}/
    course.yaml              ← course metadata
    {week-slug}/
      week.yaml              ← week + lesson metadata
      notebooks/             ← .ipynb files
      materials/             ← PDFs, slides, cheat sheets
```

## How it syncs to the database

Run from `backend/`:

```
uv run python -m app.scripts.sync_course_content
```

The sync script:
1. Reads every `course.yaml` → upserts a row in `courses`.
2. Reads every `week.yaml` → upserts `lessons` (one per lesson + one per checkpoint).
3. Each `resources:` entry → upserts a row in `lesson_resources` with the
   repo-relative path. Resolution to a Colab/download URL happens at
   request time in the API layer, gated by enrollment.

## Notebook naming convention

`{week:02}_{day:02}_{seq:02}_{slug}.ipynb` — e.g. `01_01_02_generators.ipynb`.
Checkpoints: `{week:02}_{day:02}_CK_checkpoint.ipynb`.

## Why this folder is outside `app/`

Course content is user-facing data, not Python source. Keeping it out of the
`app/` package means it isn't imported, isn't shipped in the Python wheel, and
can be mounted as a separate Docker volume in production.
