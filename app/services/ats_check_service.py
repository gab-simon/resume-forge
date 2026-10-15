"""ATS check service functions.

The check reads the PDF the way a parser does, with ``pdftotext``, and
verifies that the text keeps the reading order, the accents and the contact
data of the resume.
"""

import re
import unicodedata
from dataclasses import dataclass, field
from enum import StrEnum
from pathlib import Path

from app.infra.context import IContext
from app.infra.process import run_command
from app.services.render_service import ResumeView

# Spacing accents (cedilla, tilde, acute, grave, diaeresis, circumflex, caron,
# breve and ring) that pdfLaTeX draws as a separate glyph when the font
# encoding is not T1, so the letter and the accent are extracted apart.
_DETACHED_ACCENTS = re.compile(r'[\u00b8\u02dc\u00b4`\u00a8\u02c6\u02c7\u02d8\u02da]')
# Ligatures (ff, fi, fl, ffi, ffl, long st, st) extracted as one character
# when ``glyphtounicode`` is missing.
_LIGATURES = re.compile(r'[\ufb00-\ufb06]')
_HEADER_LINES = 6


class AtsIssueCode(StrEnum):
    """Problem found in the extracted text."""

    EMPTY_TEXT = 'empty_text'
    MISSING_SECTION = 'missing_section'
    SECTION_OUT_OF_ORDER = 'section_out_of_order'
    DETACHED_ACCENT = 'detached_accent'
    LIGATURE = 'ligature'
    REPLACEMENT_CHARACTER = 'replacement_character'
    MISSING_CONTACT = 'missing_contact'
    CONTACT_OUT_OF_HEADER = 'contact_out_of_header'


@dataclass(frozen=True, slots=True)
class AtsIssue:
    """Problem found in the extracted text."""

    code: AtsIssueCode
    message: str


@dataclass(frozen=True, slots=True)
class AtsReport:
    """Result of the ATS check of one PDF."""

    text: str
    issues: list[AtsIssue] = field(default_factory=list)

    @property
    def passed(self) -> bool:
        """Whether the extracted text has no issue."""
        return not self.issues


class PdfTextExtractionError(RuntimeError):
    """Raised when ``pdftotext`` cannot read the PDF."""


def _normalize(value: str) -> str:
    return ' '.join(unicodedata.normalize('NFC', value).split()).casefold()


def _check_sections(text: str, view: ResumeView) -> list[AtsIssue]:
    lines = [_normalize(line) for line in text.splitlines()]
    issues: list[AtsIssue] = []
    last_position = -1
    for section in view.sections:
        title = _normalize(section.title)
        position = next(
            (index for index, line in enumerate(lines) if line == title), None
        )
        if position is None:
            issues.append(
                AtsIssue(
                    AtsIssueCode.MISSING_SECTION,
                    f'Section title "{section.title}" is not a line of its own.',
                )
            )
            continue
        if position < last_position:
            issues.append(
                AtsIssue(
                    AtsIssueCode.SECTION_OUT_OF_ORDER,
                    f'Section "{section.title}" is out of the reading order.',
                )
            )
        last_position = max(last_position, position)
    return issues


def _check_characters(text: str) -> list[AtsIssue]:
    issues: list[AtsIssue] = []
    if accents := sorted(set(_DETACHED_ACCENTS.findall(text))):
        issues.append(
            AtsIssue(
                AtsIssueCode.DETACHED_ACCENT,
                f'Accents extracted apart from their letters: {" ".join(accents)}. '
                'Use \\usepackage[T1]{fontenc}.',
            )
        )
    if _LIGATURES.search(text):
        issues.append(
            AtsIssue(
                AtsIssueCode.LIGATURE,
                'Ligatures extracted as single characters. '
                'Use \\input{glyphtounicode} and \\pdfgentounicode=1.',
            )
        )
    if '�' in text:
        issues.append(
            AtsIssue(
                AtsIssueCode.REPLACEMENT_CHARACTER,
                'The text has characters without a Unicode mapping.',
            )
        )
    return issues


def _check_contact(text: str, view: ResumeView) -> list[AtsIssue]:
    normalized = _normalize(text)
    header = _normalize('\n'.join(text.strip().splitlines()[:_HEADER_LINES]))
    issues: list[AtsIssue] = []
    for label, value in (('name', view.name), ('email', view.email)):
        expected = _normalize(value)
        if expected not in normalized:
            issues.append(
                AtsIssue(
                    AtsIssueCode.MISSING_CONTACT,
                    f'The {label} "{value}" is not in the extracted text.',
                )
            )
        elif expected not in header:
            issues.append(
                AtsIssue(
                    AtsIssueCode.CONTACT_OUT_OF_HEADER,
                    f'The {label} "{value}" is not at the top of page 1.',
                )
            )
    return issues


def analyze_text(text: str, view: ResumeView) -> AtsReport:
    """Check the text extracted from a resume PDF.

    Parameters
    ----------
    text : str
        Text returned by ``pdftotext``.
    view : ResumeView
        Resume the PDF was built from, in the same language.

    Returns
    -------
    AtsReport
        The text and every issue found.
    """
    if not text.strip():
        return AtsReport(
            text=text,
            issues=[
                AtsIssue(
                    AtsIssueCode.EMPTY_TEXT,
                    'No text was extracted. The PDF may contain only images.',
                )
            ],
        )
    return AtsReport(
        text=text,
        issues=[
            *_check_contact(text, view),
            *_check_sections(text, view),
            *_check_characters(text),
        ],
    )


async def extract_text(ctx: IContext, *, pdf_path: Path) -> str:
    """Extract the text of a PDF in reading order.

    Parameters
    ----------
    ctx : IContext
        Application context for the operation.
    pdf_path : Path
        PDF to read.

    Returns
    -------
    str
        Text extracted by ``pdftotext -layout``.

    Raises
    ------
    PdfTextExtractionError
        If ``pdftotext`` fails.
    """
    result = await run_command(
        [ctx.settings.pdftotext_command, '-layout', '-enc', 'UTF-8', str(pdf_path), '-']
    )
    if result.returncode != 0:
        raise PdfTextExtractionError(result.stderr.decode('utf-8', errors='replace'))
    return result.stdout.decode('utf-8', errors='replace')


async def check(ctx: IContext, view: ResumeView, *, pdf_path: Path) -> AtsReport:
    """Extract the text of a resume PDF and check it.

    Parameters
    ----------
    ctx : IContext
        Application context for the operation.
    view : ResumeView
        Resume the PDF was built from, in the same language.
    pdf_path : Path
        PDF to check.

    Returns
    -------
    AtsReport
        The extracted text and every issue found.
    """
    text = await extract_text(ctx, pdf_path=pdf_path)
    return analyze_text(text, view)


__all__ = (
    'AtsIssue',
    'AtsIssueCode',
    'AtsReport',
    'PdfTextExtractionError',
    'analyze_text',
    'check',
    'extract_text',
)
