"""Email delivery."""

import asyncio
import smtplib
from dataclasses import dataclass
from email.message import EmailMessage as MimeMessage
from email.utils import parseaddr
from typing import Protocol

from loguru import logger

from app.infra.settings import Settings


class EmailDeliveryError(RuntimeError):
    """Raised when an email cannot be delivered."""


@dataclass(frozen=True, slots=True)
class EmailMessage:
    """Plain-text email."""

    to: str
    subject: str
    text: str


class EmailSender(Protocol):
    """Gateway that delivers emails."""

    async def send(self, message: EmailMessage) -> None:
        """Deliver one email."""
        ...


class SmtpEmailSender:
    """Deliver emails through an SMTP server."""

    def __init__(self, settings: Settings) -> None:
        if not settings.smtp_host:
            raise EmailDeliveryError('SMTP_HOST is not configured.')
        self._settings = settings

    def _send_blocking(self, message: EmailMessage) -> None:
        settings = self._settings
        mime = MimeMessage()
        mime['From'] = settings.email_from
        mime['To'] = message.to
        mime['Subject'] = message.subject
        mime.set_content(message.text)

        with smtplib.SMTP(
            settings.smtp_host or '',
            settings.smtp_port,
            timeout=settings.smtp_timeout_seconds,
        ) as client:
            if settings.smtp_starttls:
                client.starttls()
            if settings.smtp_username and settings.smtp_password:
                client.login(
                    settings.smtp_username,
                    settings.smtp_password.get_secret_value(),
                )
            client.send_message(mime)

    async def send(self, message: EmailMessage) -> None:
        """Deliver one email in a worker thread.

        Parameters
        ----------
        message : EmailMessage
            Email to deliver.

        Raises
        ------
        EmailDeliveryError
            If the SMTP server refuses the email or cannot be reached.
        """
        try:
            await asyncio.to_thread(self._send_blocking, message)
        except (smtplib.SMTPException, OSError) as exc:
            raise EmailDeliveryError('Could not deliver the email.') from exc


class ConsoleEmailSender:
    """Write emails to the log instead of sending them. Local development only."""

    async def send(self, message: EmailMessage) -> None:
        """Log one email, including its body.

        Parameters
        ----------
        message : EmailMessage
            Email to log.
        """
        _, address = parseaddr(message.to)
        logger.warning(
            'EMAIL_BACKEND=console: email to {to} not sent.\n{subject}\n{text}',
            to=address,
            subject=message.subject,
            text=message.text,
        )


def get_email_sender(settings: Settings) -> EmailSender:
    """Build the sender selected by ``EMAIL_BACKEND``.

    Parameters
    ----------
    settings : Settings
        Application settings.

    Returns
    -------
    EmailSender
        The SMTP sender, or the console sender for local development.
    """
    if settings.email_backend == 'console':
        return ConsoleEmailSender()
    return SmtpEmailSender(settings)


__all__ = (
    'ConsoleEmailSender',
    'EmailDeliveryError',
    'EmailMessage',
    'EmailSender',
    'SmtpEmailSender',
    'get_email_sender',
)
