"""Resume rendering service functions.

``cv.yaml`` becomes a view localized in one language, Jinja2 renders the view
into LaTeX and plain text, and pdfLaTeX compiles the LaTeX into a PDF.
"""

import re
from dataclasses import dataclass, field
from pathlib import Path

from jinja2 import Environment, FileSystemLoader, StrictUndefined, TemplateNotFound

from app.infra.context import IContext
from app.infra.process import run_command
from app.models.resume import (
    Education,
    Experience,
    Lang,
    Resume,
    SectionName,
    localize,
)

TEMPLATE_FILE_NAME = 'resume.tex.j2'
TEXT_TEMPLATE_PATH = '_shared/resume.txt.j2'
OUTPUT_STEM = 'cv'
_LOG_TAIL_LINES = 30

SECTION_TITLES: dict[Lang, dict[SectionName, str]] = {
    'pt': {
        SectionName.SUMMARY: 'Resumo',
        SectionName.EXPERIENCE: 'Experiência Profissional',
        SectionName.PROJECTS: 'Projetos',
        SectionName.SKILLS: 'Habilidades Técnicas',
        SectionName.EDUCATION: 'Formação Acadêmica',
        SectionName.CERTIFICATIONS: 'Certificações',
        SectionName.LANGUAGES: 'Idiomas',
    },
    'en': {
        SectionName.SUMMARY: 'Summary',
        SectionName.EXPERIENCE: 'Experience',
        SectionName.PROJECTS: 'Projects',
        SectionName.SKILLS: 'Technical Skills',
        SectionName.EDUCATION: 'Education',
        SectionName.CERTIFICATIONS: 'Certifications',
        SectionName.LANGUAGES: 'Languages',
    },
}
_PRESENT: dict[Lang, str] = {'pt': 'Atual', 'en': 'Present'}
_TECHNOLOGIES: dict[Lang, str] = {'pt': 'Tecnologias', 'en': 'Technologies'}
_MONTHS_EN = (
    'Jan', 'Feb', 'Mar', 'Apr', 'May', 'Jun',
    'Jul', 'Aug', 'Sep', 'Oct', 'Nov', 'Dec',
)  # fmt: skip

_LATEX_SPECIAL_CHARACTERS = {
    '\\': r'\textbackslash{}',
    '&': r'\&',
    '%': r'\%',
    '$': r'\$',
    '#': r'\#',
    '_': r'\_',
    '{': r'\{',
    '}': r'\}',
    '~': r'\textasciitilde{}',
    '^': r'\textasciicircum{}',
}
_LATEX_SPECIAL_PATTERN = re.compile('|'.join(map(re.escape, _LATEX_SPECIAL_CHARACTERS)))


class TemplateNotFoundError(LookupError):
    """Raised when a resume template does not exist."""

    def __init__(self, template: str) -> None:
        self.template = template
        super().__init__(f'Template not found: {template}')


class LatexCompilationError(RuntimeError):
    """Raised when pdfLaTeX fails to compile the resume."""

    def __init__(self, log_tail: str) -> None:
        self.log_tail = log_tail
        super().__init__(f'LaTeX compilation failed:\n{log_tail}')


@dataclass(frozen=True, slots=True)
class ExperienceView:
    """Experience localized for rendering."""

    company: str
    title: str
    location: str | None
    period: str
    bullets: list[str]
    technologies: list[str]


@dataclass(frozen=True, slots=True)
class ProjectView:
    """Project localized for rendering."""

    name: str
    url: str | None
    description: str
    technologies: list[str]


@dataclass(frozen=True, slots=True)
class SkillGroupView:
    """Skill category localized for rendering."""

    category: str
    items: list[str]


@dataclass(frozen=True, slots=True)
class EducationView:
    """Education localized for rendering."""

    institution: str
    degree: str
    period: str


@dataclass(frozen=True, slots=True)
class SectionView:
    """Section shown in the resume, with its standard title."""

    name: SectionName
    title: str


@dataclass(frozen=True, slots=True)
class ResumeView:
    """Resume localized in one language, ready for the templates."""

    lang: Lang
    name: str
    headline: str
    location: str
    email: str
    phone: str | None
    links: list[str]
    summary: str | None
    sections: list[SectionView]
    experience: list[ExperienceView] = field(default_factory=list)
    projects: list[ProjectView] = field(default_factory=list)
    skills: list[SkillGroupView] = field(default_factory=list)
    education: list[EducationView] = field(default_factory=list)
    certifications: list[str] = field(default_factory=list)
    languages: list[str] = field(default_factory=list)
    technologies_label: str = ''
    keywords: list[str] = field(default_factory=list)


@dataclass(frozen=True, slots=True)
class TemplateInfo:
    """Resume template available in the templates directory."""

    name: str
    path: Path


@dataclass(frozen=True, slots=True)
class BuildResult:
    """Files produced by one build."""

    template: str
    lang: Lang
    tex_path: Path
    pdf_path: Path
    txt_path: Path


class LatexRaw(str):  # ruff: ignore[subclass-builtin]
    """Text already written in LaTeX, which the renderer does not escape."""

    __slots__ = ()


def escape_latex(value: object) -> str:
    """Escape the characters that LaTeX treats as commands.

    Parameters
    ----------
    value : object
        Value to write in a LaTeX document.

    Returns
    -------
    str
        The text with special characters escaped. ``LatexRaw`` values and
        ``None`` (as an empty string) are returned unchanged.
    """
    if value is None:
        return ''
    if isinstance(value, LatexRaw):
        return value
    return _LATEX_SPECIAL_PATTERN.sub(
        lambda match: _LATEX_SPECIAL_CHARACTERS[match.group()], str(value)
    )


def latex_url(value: str) -> LatexRaw:
    r"""Build the target of a ``\\href`` from visible link text.

    Parameters
    ----------
    value : str
        Link such as ``github.com/user`` or a full URL.

    Returns
    -------
    LatexRaw
        The URL with a scheme and with ``%`` and ``#`` escaped.
    """
    url = value if re.match(r'^[a-z]+:', value) else f'https://{value}'
    if '@' in value and '/' not in value:
        url = f'mailto:{value}'
    return LatexRaw(url.replace('%', r'\%').replace('#', r'\#'))


def format_date(value: str, lang: Lang) -> str:
    """Format a ``YYYY`` or ``YYYY-MM`` date for the resume.

    Parameters
    ----------
    value : str
        Date written in ``cv.yaml``.
    lang : Lang
        Language of the resume.

    Returns
    -------
    str
        ``03/2022`` in Portuguese, ``Mar 2022`` in English, or only the year.
    """
    year, _, month = value.partition('-')
    if not month:
        return year
    if lang == 'pt':
        return f'{month}/{year}'
    return f'{_MONTHS_EN[int(month) - 1]} {year}'


def format_period(start: str | None, end: str | None, lang: Lang) -> str:
    """Format a date range, using the current label when it has no end.

    Parameters
    ----------
    start : str | None
        First date, or ``None`` to show only the end.
    end : str | None
        Last date, or ``None`` when it is current.
    lang : Lang
        Language of the resume.

    Returns
    -------
    str
        A range such as ``Mar 2022 – Present``.
    """
    finish = _PRESENT[lang] if end is None else format_date(end, lang)
    if start is None:
        return finish
    return f'{format_date(start, lang)} – {finish}'


def _experience_view(experience: Experience, lang: Lang) -> ExperienceView:
    return ExperienceView(
        company=experience.company,
        title=localize(experience.title, lang),
        location=(
            None if experience.location is None else localize(experience.location, lang)
        ),
        period=format_period(experience.start, experience.end, lang),
        bullets=[localize(bullet.text, lang) for bullet in experience.bullets],
        technologies=experience.technologies,
    )


def _education_view(education: Education, lang: Lang) -> EducationView:
    return EducationView(
        institution=education.institution,
        degree=localize(education.degree, lang),
        period=format_period(education.start, education.end, lang),
    )


def build_view(resume: Resume, lang: Lang) -> ResumeView:
    """Localize a resume and drop the sections that have no content.

    Parameters
    ----------
    resume : Resume
        Validated resume.
    lang : Lang
        Language of the output.

    Returns
    -------
    ResumeView
        The resume in ``lang``, with sections in ``section_order``.
    """
    has_content = {
        SectionName.SUMMARY: resume.summary is not None,
        SectionName.EXPERIENCE: bool(resume.experience),
        SectionName.PROJECTS: bool(resume.projects),
        SectionName.SKILLS: bool(resume.skills),
        SectionName.EDUCATION: bool(resume.education),
        SectionName.CERTIFICATIONS: bool(resume.certifications),
        SectionName.LANGUAGES: bool(resume.languages),
    }
    sections = [
        SectionView(name=name, title=SECTION_TITLES[lang][name])
        for name in dict.fromkeys(resume.section_order)
        if has_content[name]
    ]
    skills = [
        SkillGroupView(category=localize(group.category, lang), items=group.items)
        for group in resume.skills
    ]
    return ResumeView(
        lang=lang,
        name=resume.basics.name,
        headline=localize(resume.basics.headline, lang),
        location=resume.basics.location,
        email=resume.basics.email,
        phone=resume.basics.phone,
        links=resume.basics.links,
        summary=None if resume.summary is None else localize(resume.summary, lang),
        sections=sections,
        experience=[_experience_view(item, lang) for item in resume.experience],
        projects=[
            ProjectView(
                name=project.name,
                url=project.url,
                description=localize(project.description, lang),
                technologies=project.technologies,
            )
            for project in resume.projects
        ],
        skills=skills,
        education=[_education_view(item, lang) for item in resume.education],
        certifications=[
            f'{item.name} – {item.issuer}, {item.year}'
            for item in resume.certifications
        ],
        languages=[
            f'{localize(item.name, lang)}: {localize(item.level, lang)}'
            for item in resume.languages
        ],
        technologies_label=_TECHNOLOGIES[lang],
        keywords=list(dict.fromkeys(item for group in skills for item in group.items)),
    )


def _latex_environment(templates_dir: Path) -> Environment:
    # Delimiters that do not clash with the braces and percent signs of LaTeX.
    return Environment(
        loader=FileSystemLoader(templates_dir),
        block_start_string='((*',
        block_end_string='*))',
        variable_start_string='<<',
        variable_end_string='>>',
        comment_start_string='((#',
        comment_end_string='#))',
        trim_blocks=True,
        lstrip_blocks=True,
        keep_trailing_newline=True,
        undefined=StrictUndefined,
        finalize=escape_latex,
        autoescape=False,  # ruff: ignore[jinja2-autoescape-false]
    )


def _text_environment(templates_dir: Path) -> Environment:
    return Environment(
        loader=FileSystemLoader(templates_dir),
        trim_blocks=True,
        lstrip_blocks=True,
        keep_trailing_newline=True,
        undefined=StrictUndefined,
        autoescape=False,  # ruff: ignore[jinja2-autoescape-false]
    )


def list_templates(ctx: IContext) -> list[TemplateInfo]:
    """List the resume templates.

    A template is a directory of ``RESUME_TEMPLATES_DIR`` that contains
    ``resume.tex.j2``. Directories starting with ``_`` hold shared parts.

    Parameters
    ----------
    ctx : IContext
        Application context for the operation.

    Returns
    -------
    list[TemplateInfo]
        Templates sorted by name.
    """
    templates_dir = ctx.settings.resume_templates_dir
    if not templates_dir.is_dir():
        return []
    return [
        TemplateInfo(name=path.name, path=path)
        for path in sorted(templates_dir.iterdir())
        if not path.name.startswith('_') and (path / TEMPLATE_FILE_NAME).is_file()
    ]


def render_tex(ctx: IContext, view: ResumeView, *, template: str) -> str:
    """Render a resume view into a LaTeX document.

    Parameters
    ----------
    ctx : IContext
        Application context for the operation.
    view : ResumeView
        Localized resume.
    template : str
        Name of the template directory.

    Returns
    -------
    str
        LaTeX source of the resume.

    Raises
    ------
    TemplateNotFoundError
        If the template does not exist.
    """
    if template not in {item.name for item in list_templates(ctx)}:
        raise TemplateNotFoundError(template)
    environment = _latex_environment(ctx.settings.resume_templates_dir)
    environment.filters['url'] = latex_url
    try:
        jinja_template = environment.get_template(f'{template}/{TEMPLATE_FILE_NAME}')
    except TemplateNotFound as exc:
        raise TemplateNotFoundError(template) from exc
    return jinja_template.render(cv=view)


def render_text(ctx: IContext, view: ResumeView) -> str:
    """Render a resume view into plain text, to paste in ATS forms.

    Parameters
    ----------
    ctx : IContext
        Application context for the operation.
    view : ResumeView
        Localized resume.

    Returns
    -------
    str
        Plain text of the resume, in the reading order of the PDF.
    """
    environment = _text_environment(ctx.settings.resume_templates_dir)
    return environment.get_template(TEXT_TEMPLATE_PATH).render(cv=view)


def _log_tail(output: bytes, log_path: Path) -> str:
    text = (
        log_path.read_text(encoding='utf-8', errors='replace')
        if log_path.is_file()
        else output.decode('utf-8', errors='replace')
    )
    return '\n'.join(text.splitlines()[-_LOG_TAIL_LINES:])


async def compile_pdf(ctx: IContext, *, tex_path: Path) -> Path:
    """Compile a LaTeX file into a PDF next to it.

    Parameters
    ----------
    ctx : IContext
        Application context for the operation.
    tex_path : Path
        LaTeX source to compile.

    Returns
    -------
    Path
        Path of the PDF.

    Raises
    ------
    LatexCompilationError
        If pdfLaTeX exits with an error.
    """
    settings = ctx.settings
    result = await run_command(
        [
            settings.latex_command,
            '-interaction=nonstopmode',
            '-halt-on-error',
            '-file-line-error',
            f'-output-directory={tex_path.parent}',
            tex_path.name,
        ],
        cwd=tex_path.parent,
        timeout_seconds=settings.latex_timeout_seconds,
    )
    pdf_path = tex_path.with_suffix('.pdf')
    if result.returncode != 0 or not pdf_path.is_file():
        raise LatexCompilationError(
            _log_tail(result.stdout, tex_path.with_suffix('.log'))
        )
    return pdf_path


async def build(
    ctx: IContext,
    resume: Resume,
    *,
    template: str,
    lang: Lang,
    output_dir: Path | None = None,
) -> BuildResult:
    """Build the LaTeX, PDF and plain-text files of a resume.

    Parameters
    ----------
    ctx : IContext
        Application context for the operation.
    resume : Resume
        Validated resume.
    template : str
        Name of the template directory.
    lang : Lang
        Language of the output.
    output_dir : Path | None, optional
        Directory of the files. The default is
        ``RESUME_OUTPUT_DIR/<template>/<lang>``.

    Returns
    -------
    BuildResult
        Paths of the generated files.
    """
    view = build_view(resume, lang)
    tex = render_tex(ctx, view, template=template)
    text = render_text(ctx, view)

    directory = output_dir or ctx.settings.resume_output_dir / template / lang
    directory.mkdir(parents=True, exist_ok=True)
    tex_path = directory / f'{OUTPUT_STEM}.tex'
    txt_path = directory / f'{OUTPUT_STEM}.txt'
    tex_path.write_text(tex, encoding='utf-8')
    txt_path.write_text(text, encoding='utf-8')

    pdf_path = await compile_pdf(ctx, tex_path=tex_path)
    return BuildResult(
        template=template,
        lang=lang,
        tex_path=tex_path,
        pdf_path=pdf_path,
        txt_path=txt_path,
    )


__all__ = (
    'SECTION_TITLES',
    'BuildResult',
    'LatexCompilationError',
    'LatexRaw',
    'ResumeView',
    'TemplateInfo',
    'TemplateNotFoundError',
    'build',
    'build_view',
    'compile_pdf',
    'escape_latex',
    'format_date',
    'format_period',
    'latex_url',
    'list_templates',
    'render_tex',
    'render_text',
)
