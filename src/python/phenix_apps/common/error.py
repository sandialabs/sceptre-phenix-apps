class PhenixError(Exception):
    """phenix exception class."""


class AppError(PhenixError):
    """Application exception class."""


class ScheduleError(PhenixError):
    """Schedule exception class."""
