"""Unit tests for the ATS check service."""

# ruff:file-ignore[suspicious-subprocess-import]

import subprocess
from pathlib import Path
from unittest.mock import AsyncMock

import pytest

from app.services import ats_check_service, render_service
from app.services.ats_check_service import AtsIssueCode, PdfTextExtractionError
from app.services.render_service import ResumeView
from tests.unit.mocks.context import make_resume, mock_context

GOOD_TEXT = """
                                 Ana Souza
                           Engenheira de Software
              São Paulo, SP | ana@example.com | github.com/ana
RESUMO
Integração contínua & 100% testes.
EXPERIÊNCIA PROFISSIONAL
Engenheira II                                               03/2022 – Atual
HABILIDADES TÉCNICAS
Linguagens: Python, Go
FORMAÇÃO ACADÊMICA
Ciência da Computação                                        2018 – Atual
"""


def _view() -> ResumeView:
    return render_service.build_view(make_resume(), 'pt')


def _codes(text: str) -> list[AtsIssueCode]:
    return [
        issue.code for issue in ats_check_service.analyze_text(text, _view()).issues
    ]


def test_analyze_text_passes_good_text() -> None:
    """Pass text with contact, ordered sections and correct accents."""
    report = ats_check_service.analyze_text(GOOD_TEXT, _view())

    assert report.passed, report.issues


def test_analyze_text_empty() -> None:
    """Report a PDF without text."""
    assert _codes('  \n') == [AtsIssueCode.EMPTY_TEXT]


def test_analyze_text_missing_section() -> None:
    """Report a section title that is not extracted."""
    assert _codes(GOOD_TEXT.replace('RESUMO\n', '')) == [AtsIssueCode.MISSING_SECTION]


def test_analyze_text_section_out_of_order() -> None:
    """Report a section extracted out of the reading order."""
    text = GOOD_TEXT.replace('RESUMO\n', '').replace(
        'FORMAÇÃO ACADÊMICA\n', 'FORMAÇÃO ACADÊMICA\nRESUMO\n'
    )

    assert AtsIssueCode.SECTION_OUT_OF_ORDER in _codes(text)


def test_analyze_text_broken_characters() -> None:
    """Report detached accents, ligatures and unmapped characters."""
    text = GOOD_TEXT + 'Integrac\u00b8a\u02dco \ufb01nal \ufffd\n'

    assert _codes(text) == [
        AtsIssueCode.DETACHED_ACCENT,
        AtsIssueCode.LIGATURE,
        AtsIssueCode.REPLACEMENT_CHARACTER,
    ]


def test_analyze_text_contact() -> None:
    """Report contact data that is missing or outside the header."""
    moved = GOOD_TEXT.replace('ana@example.com', 'x') + '\n' * 3 + 'ana@example.com\n'

    assert _codes(moved) == [AtsIssueCode.CONTACT_OUT_OF_HEADER]
    assert _codes(GOOD_TEXT.replace('Ana Souza', 'Ana')) == [
        AtsIssueCode.MISSING_CONTACT
    ]


async def test_check_runs_pdftotext(monkeypatch: pytest.MonkeyPatch) -> None:
    """Extract the text with pdftotext in layout mode."""
    run = AsyncMock(
        return_value=subprocess.CompletedProcess([], 0, GOOD_TEXT.encode(), b'')
    )
    monkeypatch.setattr(ats_check_service, 'run_command', run)

    report = await ats_check_service.check(
        mock_context(), _view(), pdf_path=Path('cv.pdf')
    )

    assert report.passed
    assert run.await_args is not None
    assert run.await_args.args[0] == [
        'pdftotext', '-layout', '-enc', 'UTF-8', 'cv.pdf', '-',
    ]  # fmt: skip


async def test_extract_text_failure(monkeypatch: pytest.MonkeyPatch) -> None:
    """Raise PdfTextExtractionError when pdftotext fails."""
    monkeypatch.setattr(
        ats_check_service,
        'run_command',
        AsyncMock(return_value=subprocess.CompletedProcess([], 1, b'', b'bad pdf')),
    )

    with pytest.raises(PdfTextExtractionError, match='bad pdf'):
        await ats_check_service.extract_text(mock_context(), pdf_path=Path('x.pdf'))
