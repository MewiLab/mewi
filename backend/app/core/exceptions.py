"""
Custom exceptions — caught by handlers in main.py so routes stay clean.
"""


class AppError(Exception):
    """Base for all domain errors."""

    def __init__(self, message: str = "An unexpected error occurred", status_code: int = 500):
        self.message = message
        self.status_code = status_code
        super().__init__(message)


class DatabaseError(AppError):
    """Supabase / Postgres write/read failures."""

    def __init__(self, message: str = "Database operation failed"):
        super().__init__(message, status_code=500)


class EmbeddingError(AppError):
    """OpenAI embedding call failures."""

    def __init__(self, message: str = "Embedding generation failed"):
        super().__init__(message, status_code=502)


class StorageError(AppError):
    """Supabase Storage upload failures."""

    def __init__(self, message: str = "File upload failed"):
        super().__init__(message, status_code=502)


class NotFoundError(AppError):
    """Resource not found."""

    def __init__(self, resource: str = "Resource"):
        super().__init__(f"{resource} not found", status_code=404)
