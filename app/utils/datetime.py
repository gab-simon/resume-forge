"""Datetime utility functions."""

import datetime


def get_current_time() -> datetime.datetime:
    """Get the current time in UTC.

    Returns
    -------
    datetime.datetime
        The current time in UTC.
    """
    return datetime.datetime.now(datetime.UTC)
