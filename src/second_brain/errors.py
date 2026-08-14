"""Shared exception types for brainctl."""


class BrainError(Exception):
    """Base class for expected, user-facing Brain errors."""


class MigrationError(BrainError):
    """A database migration could not be applied safely."""


class BackupError(BrainError):
    """Backup or restore failed safety checks."""


class DoctorError(BrainError):
    """One or more doctor checks failed."""
