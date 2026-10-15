"""Resume models.

The resume is not a database table. ``data/cv.yaml`` is the single source of
truth, and these models validate it. ``Resume.model_json_schema()`` feeds the
JSON Schema that editors use to autocomplete the YAML.
"""

from enum import StrEnum
from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field, StringConstraints

type Lang = Literal['pt', 'en']
LANGUAGES: tuple[Lang, ...] = ('pt', 'en')

# Plain text is used for every language. A mapping gives one text per
# language, and a missing language falls back to the other one.
type LocalizedText = str | dict[Lang, str]

# ``YYYY-MM`` for jobs and ``YYYY`` or ``YYYY-MM`` for education. Every date of
# a section uses the same pattern, so ATS parsers can compute the experience.
YearMonth = Annotated[str, StringConstraints(pattern=r'^\d{4}-(0[1-9]|1[0-2])$')]
YearOrYearMonth = Annotated[
    str, StringConstraints(pattern=r'^\d{4}(-(0[1-9]|1[0-2]))?$')
]
Identifier = Annotated[str, StringConstraints(pattern=r'^[a-z0-9][a-z0-9-]*$')]


class SectionName(StrEnum):
    """Sections a resume can show, in the default order."""

    SUMMARY = 'summary'
    EXPERIENCE = 'experience'
    PROJECTS = 'projects'
    SKILLS = 'skills'
    EDUCATION = 'education'
    CERTIFICATIONS = 'certifications'
    LANGUAGES = 'languages'


DEFAULT_SECTION_ORDER: tuple[SectionName, ...] = tuple(SectionName)


class ResumeModel(BaseModel):
    """Base of the resume models, which reject unknown keys."""

    model_config = ConfigDict(extra='forbid')


class Basics(ResumeModel):
    """Header of the resume. Contact data stays in the page body."""

    name: str
    headline: LocalizedText
    location: str
    email: str
    phone: str | None = None
    links: list[str] = Field(
        default_factory=list,
        description='Visible link text, such as linkedin.com/in/user.',
    )


class Bullet(ResumeModel):
    """Achievement of an experience, with tags and pre-approved variants."""

    id: Identifier
    tags: list[str] = Field(default_factory=list)
    text: LocalizedText
    variants: list[LocalizedText] = Field(default_factory=list)


class Experience(ResumeModel):
    """Position held at a company."""

    id: Identifier
    company: str
    title: LocalizedText
    location: LocalizedText | None = None
    start: YearMonth
    end: YearMonth | None = Field(default=None, description='Empty means current.')
    bullets: list[Bullet] = Field(default_factory=list)
    technologies: list[str] = Field(default_factory=list)


class Project(ResumeModel):
    """Open source, side project or relevant case."""

    id: Identifier
    name: str
    url: str | None = None
    description: LocalizedText
    tags: list[str] = Field(default_factory=list)
    technologies: list[str] = Field(default_factory=list)


class SkillGroup(ResumeModel):
    """Category of technical skills."""

    category: LocalizedText
    items: list[str]


class Education(ResumeModel):
    """Degree or course."""

    institution: str
    degree: LocalizedText
    start: YearOrYearMonth | None = None
    end: YearOrYearMonth | None = Field(
        default=None, description='Empty means in progress.'
    )


class Certification(ResumeModel):
    """Certification with its official name, issuer and year."""

    name: str
    issuer: str
    year: int


class Language(ResumeModel):
    """Spoken language and level."""

    name: LocalizedText
    level: LocalizedText


class Resume(ResumeModel):
    """Whole resume, as written in ``data/cv.yaml``."""

    basics: Basics
    summary: LocalizedText | None = None
    experience: list[Experience] = Field(default_factory=list)
    projects: list[Project] = Field(default_factory=list)
    skills: list[SkillGroup] = Field(default_factory=list)
    education: list[Education] = Field(default_factory=list)
    certifications: list[Certification] = Field(default_factory=list)
    languages: list[Language] = Field(default_factory=list)
    section_order: list[SectionName] = Field(
        default_factory=lambda: list(DEFAULT_SECTION_ORDER),
        description='Sections in the order they appear. Omitted ones are hidden.',
    )


def localize(value: LocalizedText, lang: Lang) -> str:
    """Return the text of a localized value in one language.

    Parameters
    ----------
    value : LocalizedText
        Plain text or a mapping from language to text.
    lang : Lang
        Language requested.

    Returns
    -------
    str
        The text in ``lang``, or in the other language when it is missing.
    """
    if isinstance(value, str):
        return value
    if lang in value:
        return value[lang]
    return next(iter(value.values()), '')


__all__ = (
    'DEFAULT_SECTION_ORDER',
    'LANGUAGES',
    'Basics',
    'Bullet',
    'Certification',
    'Education',
    'Experience',
    'Lang',
    'Language',
    'LocalizedText',
    'Project',
    'Resume',
    'SectionName',
    'SkillGroup',
    'localize',
)
