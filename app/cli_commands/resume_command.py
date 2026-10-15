"""Resume commands."""

import asyncio
from collections.abc import Coroutine
from pathlib import Path
from typing import Annotated, Any

import typer
from rich.console import Console

from app.infra.context import get_file_context
from app.infra.process import ExternalToolNotFoundError
from app.models.resume import LANGUAGES, Lang
from app.services import ats_check_service, render_service, resume_service
from app.services.render_service import LatexCompilationError, TemplateNotFoundError
from app.services.resume_service import ResumeInvalidError, ResumeNotFoundError

# ruff:file-ignore[print]

# No name: the commands are registered at the top level, as ``cv build``.
app = typer.Typer(no_args_is_help=True)
console = Console()

LangOption = Annotated[
    str,
    typer.Option('--lang', '-l', help=f'Language: {", ".join(LANGUAGES)}.'),
]
TemplateOption = Annotated[
    str, typer.Option('--template', '-t', help='Template name, see `cv templates`.')
]
_HANDLED_ERRORS = (
    ExternalToolNotFoundError,
    LatexCompilationError,
    ResumeInvalidError,
    ResumeNotFoundError,
    TemplateNotFoundError,
    ats_check_service.PdfTextExtractionError,
)


def _lang(value: str) -> Lang:
    if value not in LANGUAGES:
        raise typer.BadParameter(f'use one of: {", ".join(LANGUAGES)}')
    return value


def _print_report(report: ats_check_service.AtsReport) -> None:
    if report.passed:
        console.print('[green]ATS check passed[/green]')
        return
    console.print(f'[red]ATS check found {len(report.issues)} issue(s):[/red]')
    for issue in report.issues:
        console.print(f'  - [bold]{issue.code}[/bold]: {issue.message}')


async def _build(template: str, lang: Lang, output: Path | None, check: bool) -> bool:
    ctx = get_file_context()
    resume = await resume_service.read_resume(ctx)
    result = await render_service.build(
        ctx, resume, template=template, lang=lang, output_dir=output
    )
    console.print(f'[green]PDF[/green]  {result.pdf_path}')
    console.print(f'[green]TXT[/green]  {result.txt_path}')
    console.print(f'[green]TeX[/green]  {result.tex_path}')
    if not check:
        return True
    report = await ats_check_service.check(
        ctx, render_service.build_view(resume, lang), pdf_path=result.pdf_path
    )
    _print_report(report)
    return report.passed


def _run[T](coroutine: Coroutine[Any, Any, T]) -> T:
    try:
        return asyncio.run(coroutine)
    except _HANDLED_ERRORS as exc:
        console.print(f'[red]{exc}[/red]')
        raise typer.Exit(1) from exc


@app.command(name='build', help='Build the PDF, TXT and TeX of the master resume.')
def build_command(
    template: TemplateOption = 'classic',
    lang: LangOption = 'pt',
    output: Annotated[
        Path | None,
        typer.Option('--output', '-o', help='Output directory.'),
    ] = None,
    check: Annotated[
        bool, typer.Option('--check/--no-check', help='Run the ATS check.')
    ] = True,
) -> None:
    """Build the master resume.

    Raises
    ------
    typer.Exit
        With status 1 when the build or the ATS check fails.
    """
    passed = _run(_build(template, _lang(lang), output, check))
    if not passed:
        raise typer.Exit(1)


@app.command(name='check', help='Extract the text of a PDF and run the ATS check.')
def check_command(
    pdf: Annotated[Path, typer.Argument(exists=True, dir_okay=False)],
    lang: LangOption = 'pt',
    show_text: Annotated[
        bool, typer.Option('--show-text', help='Print the extracted text.')
    ] = False,
) -> None:
    """Check a resume PDF against the master resume.

    Raises
    ------
    typer.Exit
        With status 1 when the ATS check fails.
    """
    language = _lang(lang)

    async def _() -> ats_check_service.AtsReport:
        ctx = get_file_context()
        resume = await resume_service.read_resume(ctx)
        return await ats_check_service.check(
            ctx, render_service.build_view(resume, language), pdf_path=pdf
        )

    report = _run(_())
    if show_text:
        print(report.text)
    _print_report(report)
    if not report.passed:
        raise typer.Exit(1)


@app.command(name='templates', help='List the resume templates.')
def templates_command() -> None:
    """List the resume templates."""
    for template in render_service.list_templates(get_file_context()):
        print(template.name)


@app.command(name='schema', help='Write data/cv.schema.json for editor validation.')
def schema_command() -> None:
    """Write the JSON Schema of ``cv.yaml``."""
    path = _run(resume_service.write_json_schema(get_file_context()))
    console.print(f'[green]Schema[/green] {path}')


@app.command(name='validate', help='Validate data/cv.yaml.')
def validate_command() -> None:
    """Validate the master resume."""
    _run(resume_service.read_resume(get_file_context()))
    console.print('[green]cv.yaml is valid[/green]')
