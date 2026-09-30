class AppError(Exception):
    """Base class for failures the application raises on purpose."""


class InputRejectedError(AppError):
    """The request was refused by the input guard. The message is safe to return."""


class ToolError(AppError):
    """A tool could not do its job. The message is safe to show to the model."""


class LLMError(AppError):
    """The model call failed or returned something unusable."""

    def __init__(self, message: str, *, retryable: bool = False) -> None:
        super().__init__(message)
        self.retryable = retryable
