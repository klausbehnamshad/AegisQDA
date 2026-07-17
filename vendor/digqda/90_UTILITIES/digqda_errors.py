"""Shared, user-actionable errors for the local DigQDA workflow."""


class WorkflowError(RuntimeError):
    """A user-actionable, fail-closed pipeline error."""
