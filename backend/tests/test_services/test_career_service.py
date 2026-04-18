"""Unit tests for pure career service helpers (#171, #172 — no DB required)."""
import pytest

from app.services.career_service import (
    compute_fit_score,
    compute_skill_gap,
    extract_jd_skills,
)


def test_fit_score_perfect_match() -> None:
    student_skills = {"python": 0.9, "llm": 0.85, "fastapi": 0.8}
    jd_skills = ["python", "llm"]
    score = compute_fit_score(student_skills, jd_skills)
    assert score >= 0.85


def test_fit_score_no_match() -> None:
    student_skills = {"python": 0.9}
    jd_skills = ["java", "kubernetes"]
    score = compute_fit_score(student_skills, jd_skills)
    assert score == 0.0


def test_fit_score_partial() -> None:
    student_skills = {"python": 0.9, "llm": 0.3}
    jd_skills = ["python", "llm", "docker"]
    score = compute_fit_score(student_skills, jd_skills)
    assert 0.0 < score < 1.0


def test_fit_score_empty_jd_skills() -> None:
    student_skills = {"python": 0.9}
    jd_skills: list[str] = []
    score = compute_fit_score(student_skills, jd_skills)
    assert score == 0.0


def test_skill_gap_identifies_missing() -> None:
    student_skills = {"python": 0.9}
    jd_skills = ["python", "docker", "kubernetes"]
    gap = compute_skill_gap(student_skills, jd_skills)
    assert "docker" in gap
    assert "kubernetes" in gap
    assert "python" not in gap


def test_skill_gap_partial_mastery_below_threshold() -> None:
    student_skills = {"python": 0.5}  # below 0.7 threshold
    jd_skills = ["python"]
    gap = compute_skill_gap(student_skills, jd_skills)
    assert "python" in gap


def test_skill_gap_all_mastered() -> None:
    student_skills = {"python": 0.9, "fastapi": 0.8}
    jd_skills = ["python", "fastapi"]
    gap = compute_skill_gap(student_skills, jd_skills)
    assert gap == []


def test_extract_jd_skills_basic() -> None:
    jd = "We need Python, FastAPI, and experience with LLMs."
    skills = extract_jd_skills(jd)
    assert len(skills) > 0
    assert any("python" in s.lower() for s in skills)


def test_extract_jd_skills_multiple() -> None:
    jd = "Must know Docker, Kubernetes and have REST API experience with PostgreSQL."
    skills = extract_jd_skills(jd)
    assert "docker" in skills
    assert "kubernetes" in skills
    assert "postgresql" in skills


def test_extract_jd_skills_empty() -> None:
    jd = "We need someone awesome."
    skills = extract_jd_skills(jd)
    assert isinstance(skills, list)


def test_fit_score_case_insensitive() -> None:
    student_skills = {"python": 0.9}
    jd_skills = ["Python"]  # JD uses title case
    score = compute_fit_score(student_skills, jd_skills)
    assert score == pytest.approx(0.9)
