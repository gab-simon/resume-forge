"""Unit tests for the render service."""

# ruff:file-ignore[suspicious-subprocess-import]

import subprocess
from pathlib import Path
from unittest.mock import AsyncMock

import pytest

from app.models.resume import SectionName
from app.services import render_service
from app.services.render_service import (
    LatexCompilationError,
    LatexRaw,
    TemplateNotFoundError,
)
from tests.unit.mocks.context import make_resume, make_settings, mock_context


@pytest.mark.parametrize(
    ('value', 'expected'),
    [
        (
            'R&D 100% #1 $5 a_b {x} ~ ^',
            r'R\&D 100\% \#1 \$5 a\_b \{x\} \textasciitilde{} \textasciicircum{}',
        ),
        ('C:\\path', r'C:\textbackslash{}path'),
        (None, ''),
        (LatexRaw(r'\textbf{x}'), r'\textbf{x}'),
        ('ção', 'ção'),
    ],
)  # fmt: skip
def test_escape_latex(value: object, expected: str) -> None:
    """Escape LaTeX special characters and keep accents and raw LaTeX."""
    assert render_service.escape_latex(value) == expected


@pytest.mark.parametrize(
    ('value', 'expected'),
    [
        ('github.com/ana', 'https://github.com/ana'),
        ('https://x.dev/a#b', r'https://x.dev/a\#b'),
        ('ana@example.com', 'mailto:ana@example.com'),
    ],
)
def test_latex_url(value: str, expected: str) -> None:
    """Add a scheme to visible link text and escape the URL."""
    assert render_service.latex_url(value) == expected


def test_format_period() -> None:
    """Format date ranges in each language."""
    assert render_service.format_period('2022-03', None, 'pt') == '03/2022 – Atual'
    assert render_service.format_period('2022-03', None, 'en') == 'Mar 2022 – Present'
    assert render_service.format_period('2021', '2025', 'en') == '2021 – 2025'
    assert render_service.format_period(None, '2020-12', 'en') == 'Dec 2020'


def test_build_view_localizes_and_orders_sections() -> None:
    """Localize the resume and keep only ordered sections with content."""
    resume = make_resume(section_order=['skills', 'experience', 'projects'])

    view = render_service.build_view(resume, 'en')

    assert view.headline == 'Software Engineer'
    assert view.summary == 'CI & tests.'
    # Projects is empty and summary is not in the order, so both are hidden.
    assert [section.name for section in view.sections] == [
        SectionName.SKILLS,
        SectionName.EXPERIENCE,
    ]
    assert view.sections[0].title == 'Technical Skills'
    # A category without English falls back to Portuguese.
    assert view.skills[0].category == 'Linguagens'
    assert view.experience[0].period == 'Mar 2022 – Present'
    assert view.keywords == ['Python', 'Go']


def test_list_templates_skips_shared_directory() -> None:
    """List template directories, skipping shared parts."""
    names = [
        template.name for template in render_service.list_templates(mock_context())
    ]

    assert 'classic' in names
    assert '_shared' not in names


def test_list_templates_without_directory() -> None:
    """Return no template when the directory does not exist."""
    ctx = mock_context(settings=make_settings(resume_templates_dir=Path('/nope')))

    assert render_service.list_templates(ctx) == []


def test_render_tex_follows_ats_rules() -> None:
    """Render LaTeX with the ATS preamble and escaped content."""
    view = render_service.build_view(make_resume(), 'pt')

    tex = render_service.render_tex(mock_context(), view, template='classic')

    assert r'\usepackage[T1]{fontenc}' in tex
    assert r'\input{glyphtounicode}' in tex
    assert r'\pdfgentounicode=1' in tex
    assert 'fontawesome' not in tex
    assert r'Integração contínua \& 100\% testes.' in tex
    assert r'\href{mailto:ana@example.com}{ana@example.com}' in tex
    assert r'C\#' in tex
    assert '\\section{Experiência Profissional}' in tex
    assert '<<' not in tex
    assert '((*' not in tex


def test_render_tex_unknown_template() -> None:
    """Raise TemplateNotFoundError for an unknown template."""
    view = render_service.build_view(make_resume(), 'pt')

    with pytest.raises(TemplateNotFoundError):
        render_service.render_tex(mock_context(), view, template='nope')


def test_render_text_keeps_reading_order() -> None:
    """Render plain text in the reading order of the PDF."""
    view = render_service.build_view(make_resume(), 'pt')

    text = render_service.render_text(mock_context(), view)

    lines = text.splitlines()
    assert lines[0] == 'Ana Souza'
    assert 'ana@example.com' in lines[2]
    assert text.index('RESUMO') < text.index('EXPERIÊNCIA PROFISSIONAL')
    assert '- Reduzi a latência p95 de 800 ms para 180 ms.' in lines
    assert '\\' not in text


async def test_build_writes_files_and_compiles(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Write the TeX and TXT files and compile the PDF."""

    def fake_run(args: list[str], **_kwargs: object) -> subprocess.CompletedProcess:
        (tmp_path / 'cv.pdf').write_bytes(b'%PDF')
        return subprocess.CompletedProcess(args, 0, b'', b'')

    run = AsyncMock(side_effect=fake_run)
    monkeypatch.setattr(render_service, 'run_command', run)

    result = await render_service.build(
        mock_context(),
        make_resume(),
        template='classic',
        lang='en',
        output_dir=tmp_path,
    )

    assert result.pdf_path == tmp_path / 'cv.pdf'
    assert result.tex_path.read_text(encoding='utf-8').startswith('\\documentclass')
    assert result.txt_path.read_text(encoding='utf-8').startswith('Ana Souza')
    assert run.await_args is not None
    args = run.await_args.args[0]
    assert args[0] == 'pdflatex'
    assert '-halt-on-error' in args
    assert args[-1] == 'cv.tex'


async def test_build_uses_default_output_dir(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Build into RESUME_OUTPUT_DIR/<template>/<lang> by default."""
    ctx = mock_context(settings=make_settings(resume_output_dir=tmp_path))
    expected_dir = tmp_path / 'classic' / 'pt'

    def fake_run(args: list[str], **_kwargs: object) -> subprocess.CompletedProcess:
        (expected_dir / 'cv.pdf').write_bytes(b'%PDF')
        return subprocess.CompletedProcess(args, 0, b'', b'')

    monkeypatch.setattr(render_service, 'run_command', AsyncMock(side_effect=fake_run))

    result = await render_service.build(
        ctx, make_resume(), template='classic', lang='pt'
    )

    assert result.pdf_path == expected_dir / 'cv.pdf'


async def test_compile_pdf_reports_log_tail(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Raise with the end of the LaTeX log when compilation fails."""
    tex_path = tmp_path / 'cv.tex'
    tex_path.write_text('x', encoding='utf-8')
    (tmp_path / 'cv.log').write_text('line\n! Undefined control sequence.\n')
    monkeypatch.setattr(
        render_service,
        'run_command',
        AsyncMock(return_value=subprocess.CompletedProcess([], 1, b'', b'')),
    )

    with pytest.raises(LatexCompilationError) as error:
        await render_service.compile_pdf(mock_context(), tex_path=tex_path)

    assert 'Undefined control sequence' in error.value.log_tail


async def test_compile_pdf_without_log_uses_output(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Use the process output when LaTeX writes no log."""
    tex_path = tmp_path / 'cv.tex'
    monkeypatch.setattr(
        render_service,
        'run_command',
        AsyncMock(return_value=subprocess.CompletedProcess([], 1, b'fatal', b'')),
    )

    with pytest.raises(LatexCompilationError) as error:
        await render_service.compile_pdf(mock_context(), tex_path=tex_path)

    assert error.value.log_tail == 'fatal'
