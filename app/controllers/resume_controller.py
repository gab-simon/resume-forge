"""Resume HTTP controller."""

from typing import Annotated, Never

from fastapi import APIRouter, HTTPException, Query, status
from fastapi.responses import FileResponse, PlainTextResponse

from app.infra.context import FileContext
from app.infra.process import ExternalToolNotFoundError
from app.models.resume import Lang, Resume
from app.resources.resume_resource import (
    AtsIssueResource,
    AtsReportResource,
    ResumeResource,
    TemplateResource,
)
from app.services import ats_check_service, render_service, resume_service
from app.services.render_service import LatexCompilationError, TemplateNotFoundError
from app.services.resume_service import ResumeInvalidError, ResumeNotFoundError

router = APIRouter(
    prefix='/resume',
    tags=['RESUME'],
)

LangQuery = Annotated[Lang, Query(description='Language of the resume.')]
TemplateQuery = Annotated[str, Query(max_length=64, description='Template name.')]


def _raise_resume_error(exc: Exception) -> Never:
    if isinstance(exc, ResumeNotFoundError):
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail='Resume file not found.',
        ) from exc
    if isinstance(exc, ResumeInvalidError):
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail=exc.errors,
        ) from exc
    if isinstance(exc, TemplateNotFoundError):
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail=f'Template not found: {exc.template}.',
        ) from exc
    if isinstance(exc, ExternalToolNotFoundError):
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail=f'External tool not installed: {exc.tool}.',
        ) from exc
    if isinstance(exc, LatexCompilationError):
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f'LaTeX compilation failed.\n{exc.log_tail}',
        ) from exc
    raise exc


async def _read_resume(ctx: FileContext) -> Resume:
    try:
        return await resume_service.read_resume(ctx)
    except (ResumeNotFoundError, ResumeInvalidError) as exc:
        _raise_resume_error(exc)


@router.get('', response_model=ResumeResource)
async def read_resume(ctx: FileContext) -> ResumeResource:
    """Return the master resume.

    Returns
    -------
    ResumeResource
        The validated content of ``cv.yaml``.
    """
    resume = await _read_resume(ctx)
    return ResumeResource.model_validate(resume.model_dump())


@router.get('/templates', response_model=list[TemplateResource])
async def read_templates(ctx: FileContext) -> list[TemplateResource]:
    """List the resume templates.

    Returns
    -------
    list[TemplateResource]
        Templates sorted by name.
    """
    return [
        TemplateResource(name=template.name)
        for template in render_service.list_templates(ctx)
    ]


@router.get('/text', response_class=PlainTextResponse)
async def read_resume_text(ctx: FileContext, lang: LangQuery = 'pt') -> str:
    """Return the resume as plain text, to paste in ATS forms.

    Returns
    -------
    str
        Plain text of the resume.
    """
    resume = await _read_resume(ctx)
    return render_service.render_text(ctx, render_service.build_view(resume, lang))


@router.get(
    '/pdf',
    response_class=FileResponse,
    responses={200: {'content': {'application/pdf': {}}}},
)
async def build_resume_pdf(
    ctx: FileContext,
    template: TemplateQuery = 'classic',
    lang: LangQuery = 'pt',
) -> FileResponse:
    """Build the resume and return the PDF.

    Returns
    -------
    FileResponse
        The PDF of the resume.
    """
    resume = await _read_resume(ctx)
    try:
        result = await render_service.build(ctx, resume, template=template, lang=lang)
    except (
        TemplateNotFoundError,
        ExternalToolNotFoundError,
        LatexCompilationError,
    ) as exc:
        _raise_resume_error(exc)
    return FileResponse(
        result.pdf_path,
        media_type='application/pdf',
        filename=f'cv-{template}-{lang}.pdf',
        content_disposition_type='inline',
    )


@router.get('/check', response_model=AtsReportResource)
async def check_resume(
    ctx: FileContext,
    template: TemplateQuery = 'classic',
    lang: LangQuery = 'pt',
) -> AtsReportResource:
    """Build the resume and run the ATS check on its PDF.

    Returns
    -------
    AtsReportResource
        The extracted text and the issues found.
    """
    resume = await _read_resume(ctx)
    try:
        result = await render_service.build(ctx, resume, template=template, lang=lang)
        report = await ats_check_service.check(
            ctx, render_service.build_view(resume, lang), pdf_path=result.pdf_path
        )
    except (
        TemplateNotFoundError,
        ExternalToolNotFoundError,
        LatexCompilationError,
    ) as exc:
        _raise_resume_error(exc)
    return AtsReportResource(
        passed=report.passed,
        issues=[
            AtsIssueResource(code=issue.code, message=issue.message)
            for issue in report.issues
        ],
        text=report.text,
    )


__all__ = ('router',)
