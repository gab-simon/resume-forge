"""Unit tests for the resume service."""

import json
from pathlib import Path

import pytest

from app.infra.context import Context
from app.services import resume_service
from app.services.resume_service import ResumeInvalidError, ResumeNotFoundError
from tests.unit.mocks.context import make_settings, mock_context

VALID_YAML = """
basics:
  name: Ana
  headline: Dev
  location: Curitiba, PR
  email: ana@example.com
experience:
  - id: acme
    company: Acme
    title: Dev
    start: 2022-03
"""


def _context(data_dir: Path) -> Context:
    return mock_context(settings=make_settings(resume_data_dir=data_dir))


async def test_read_resume_validates_yaml(tmp_path: Path) -> None:
    """Parse cv.yaml and keep a missing end date as current."""
    (tmp_path / 'cv.yaml').write_text(VALID_YAML, encoding='utf-8')

    resume = await resume_service.read_resume(_context(tmp_path))

    assert resume.basics.name == 'Ana'
    assert resume.experience[0].start == '2022-03'
    assert resume.experience[0].end is None


async def test_read_resume_without_file_raises_not_found(tmp_path: Path) -> None:
    """Raise ResumeNotFoundError when cv.yaml does not exist."""
    with pytest.raises(ResumeNotFoundError):
        await resume_service.read_resume(_context(tmp_path))


@pytest.mark.parametrize(
    'content',
    ['- just\n- a list\n', 'basics: [unclosed\n'],
)
async def test_read_resume_rejects_non_mapping_or_broken_yaml(
    tmp_path: Path, content: str
) -> None:
    """Reject YAML that is broken or not a mapping."""
    (tmp_path / 'cv.yaml').write_text(content, encoding='utf-8')

    with pytest.raises(ResumeInvalidError):
        await resume_service.read_resume(_context(tmp_path))


async def test_read_resume_reports_field_paths(tmp_path: Path) -> None:
    """Report each schema error with the dotted path of the field."""
    (tmp_path / 'cv.yaml').write_text(
        VALID_YAML.replace('2022-03', '2022-13') + 'unknown: 1\n', encoding='utf-8'
    )

    with pytest.raises(ResumeInvalidError) as error:
        await resume_service.read_resume(_context(tmp_path))

    paths = [message.split(':', 1)[0] for message in error.value.errors]
    assert 'experience.0.start' in paths
    assert 'unknown' in paths


async def test_write_json_schema(tmp_path: Path) -> None:
    """Write the JSON Schema next to cv.yaml."""
    path = await resume_service.write_json_schema(_context(tmp_path))

    schema = json.loads(path.read_text(encoding='utf-8'))
    assert path == tmp_path / 'cv.schema.json'
    assert schema['title'] == 'Resume Forge CV'
    assert 'basics' in schema['properties']


async def test_repository_master_resume_is_valid() -> None:
    """Keep the versioned data/cv.yaml valid."""
    from app.infra.settings import ROOT_DIR

    resume = await resume_service.read_resume(_context(ROOT_DIR / 'data'))

    assert resume.experience
