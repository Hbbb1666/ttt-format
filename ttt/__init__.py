"""TTT 容器格式参考实现。"""

from .format import (  # noqa: F401
    Attachment,
    Document,
    TTTError,
    build,
    extract,
    normalize_member_path,
    parse,
    validate,
    validate_document,
)

__version__ = "0.1.0"
__all__ = [
    "Attachment",
    "Document",
    "TTTError",
    "build",
    "extract",
    "normalize_member_path",
    "parse",
    "validate",
    "validate_document",
    "__version__",
]
