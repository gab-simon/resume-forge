"""Resume HTTP resources."""

from pydantic import BaseModel

from app.models.resume import Resume


class ResumeResource(Resume):
    """HTTP representation of the master resume, as written in ``cv.yaml``."""


class TemplateResource(BaseModel):
    """HTTP representation of a resume template."""

    name: str


class AtsIssueResource(BaseModel):
    """Problem found in the text extracted from a resume PDF."""

    code: str
    message: str


class AtsReportResource(BaseModel):
    """Result of the ATS check of a built resume."""

    passed: bool
    issues: list[AtsIssueResource]
    text: str


__all__ = (
    'AtsIssueResource',
    'AtsReportResource',
    'ResumeResource',
    'TemplateResource',
)
