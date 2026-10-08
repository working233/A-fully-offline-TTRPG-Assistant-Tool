"""统一错误类型：Service 层只抛 ServiceError，由 API 层翻译成 HTTP 状态码。"""
from __future__ import annotations


class ServiceError(Exception):
    def __init__(self, message: str, code: str = "internal_error", status: int = 400, details=None):
        super().__init__(message)
        self.message = message
        self.code = code
        self.status = status
        self.details = details or {}

    def to_dict(self) -> dict:
        return {"code": self.code, "message": self.message, "details": self.details}


class NotFound(ServiceError):
    def __init__(self, message: str, details=None):
        super().__init__(message, code="not_found", status=404, details=details)


class ValidationFailed(ServiceError):
    def __init__(self, message: str, details=None):
        super().__init__(message, code="validation_failed", status=422, details=details)


class SafetyViolation(ServiceError):
    def __init__(self, message: str, details=None):
        super().__init__(message, code="safety_violation", status=403, details=details)


class Conflict(ServiceError):
    def __init__(self, message: str, details=None):
        super().__init__(message, code="conflict", status=409, details=details)
