"""Operation correlation across the Windows message thread and correction worker."""

import logging
from contextvars import ContextVar
from pathlib import PureWindowsPath
from traceback import walk_tb


operation = ContextVar("luna_operation_id", default="-")


def error_frames(error: BaseException) -> str:
    # Frame locations are enough to trace packaged startup failures without
    # logging an exception's message, local variables, or source lines.
    return " > ".join(
        f"{PureWindowsPath(frame.f_code.co_filename).name}:{line}:{frame.f_code.co_name}"
        for frame, line in walk_tb(error.__traceback__)
    )


class OperationFilter(logging.Filter):
    def filter(self, record):
        record.operation_id = operation.get()
        return True
