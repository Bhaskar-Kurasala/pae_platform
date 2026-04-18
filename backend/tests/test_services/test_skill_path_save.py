"""Unit tests for save_skill_path / get_saved_skill_path (#24)."""

import uuid

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from app.services.skill_path_service import get_saved_skill_path, save_skill_path

pytestmark = pytest.mark.asyncio


async def test_save_and_retrieve_skill_path(db_session: AsyncSession) -> None:
    """Saving a path and retrieving it returns the same skill IDs."""
    user_id = uuid.uuid4()
    skill_ids = [uuid.uuid4(), uuid.uuid4(), uuid.uuid4()]
    await save_skill_path(db_session, user_id=user_id, skill_ids=skill_ids)
    result = await get_saved_skill_path(db_session, user_id=user_id)
    assert result is not None
    assert result.skill_ids == skill_ids


async def test_save_overwrites_existing_path(db_session: AsyncSession) -> None:
    """A second save replaces the first path completely."""
    user_id = uuid.uuid4()
    first = [uuid.uuid4()]
    second = [uuid.uuid4(), uuid.uuid4()]
    await save_skill_path(db_session, user_id=user_id, skill_ids=first)
    await save_skill_path(db_session, user_id=user_id, skill_ids=second)
    result = await get_saved_skill_path(db_session, user_id=user_id)
    assert result is not None
    assert result.skill_ids == second


async def test_get_path_returns_none_for_new_user(db_session: AsyncSession) -> None:
    """A user with no saved path gets None, not an error."""
    result = await get_saved_skill_path(db_session, user_id=uuid.uuid4())
    assert result is None


async def test_save_empty_path(db_session: AsyncSession) -> None:
    """An empty skill list can be saved and retrieved."""
    user_id = uuid.uuid4()
    await save_skill_path(db_session, user_id=user_id, skill_ids=[])
    result = await get_saved_skill_path(db_session, user_id=user_id)
    assert result is not None
    assert result.skill_ids == []
