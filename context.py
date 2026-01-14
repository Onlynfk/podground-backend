from contextvars import ContextVar
from fastapi import Request

current_user_id: ContextVar[Request | None] = ContextVar(
    "current_user_id", default=None
)


def get_current_user_id() -> str | None:
    return current_user_id.get()
