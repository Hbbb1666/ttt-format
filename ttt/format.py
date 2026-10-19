"""TTT 0.1 容器格式：读写与校验（仅依赖标准库）。

布局（全部大端）::

    0   magic          4B   b"TTT1"
    4   major          u16
    6   minor          u16
    8   flags          u32
    12  header_len     u32   清单 JSON 字节数
    16  payload_len    u64   负载（ZIP）字节数
    24  body_sha256    32B   SHA-256(header || payload)
    56  header         header_len 字节，UTF-8 JSON
    ..  payload        payload_len 字节，ZIP
"""

from __future__ import annotations

import hashlib
import io
import json
import re
import struct
import zipfile
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Dict, Iterable, List, Optional

MAGIC = b"TTT1"
HEADER_SIZE = struct.calcsize(">4sHHIIQ32s")  # 56
MAX_HEADER_JSON = 1 << 20          # 1 MiB
MAX_PAYLOAD = 4 << 30              # 4 GiB
MAX_ENTRIES = 10000
MAX_UNCOMPRESSED = 2 << 30         # 2 GiB
MAX_RATIO = 20

SUPPORTED_MAJOR = frozenset({1})
SUPPORTED_MINOR = 0
KNOWN_FLAGS = 0
KNOWN_HEADER_KEYS = frozenset(
    {"schema", "major", "minor", "created", "generator", "content", "attachments"}
)
REQUIRED_HEADER_KEYS = frozenset(
    {"schema", "major", "minor", "created", "generator", "content", "attachments"}
)

_DRIVE = re.compile(r"^[A-Za-z]:")
_CTRL = re.compile(r"[\x00-\x1f\x7f]")
_SHA_HEX = re.compile(r"^[0-9a-f]{64}$")


class TTTError(Exception):
    """带规范错误码的异常。"""

    def __init__(self, code: str, message: str, detail: object = None) -> None:
        super().__init__("%s: %s" % (code, message))
        self.code = code
        self.message = message
        self.detail = detail


def normalize_member_path(path: str) -> str:
    """校验并返回 ZIP 内相对路径（规范第 5 节）。"""
    if not isinstance(path, str) or not path:
        raise TTTError("UNSAFE_PATH", "路径为空或不是字符串")
    if len(path.encode("utf-8")) > 512:
        raise TTTError("UNSAFE_PATH", "路径超过 512 字节: %r" % path)
    if path.startswith("/") or "\\" in path:
        raise TTTError("UNSAFE_PATH", "绝对路径或反斜杠: %r" % path)
    if _DRIVE.match(path):
        raise TTTError("UNSAFE_PATH", "盘符前缀: %r" % path)
    if _CTRL.search(path):
        raise TTTError("UNSAFE_PATH", "含控制字符: %r" % path)
    if any(seg in ("", ".", "..") for seg in path.split("/")):
        raise TTTError("UNSAFE_PATH", "含空段/./..: %r" % path)
    return path


@dataclass(frozen=True)
class Attachment:
    path: str
    data: bytes


@dataclass
class Document:
    major: int
    minor: int
    flags: int
    header: dict
    payload: bytes
    warnings: List[str] = field(default_factory=list)


def _canonical_json(obj: object) -> bytes:
    return json.dumps(
        obj, ensure_ascii=False, sort_keys=True, separators=(",", ":")
    ).encode("utf-8")


def _zip_bytes(files: Dict[str, bytes]) -> bytes:
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", compression=zipfile.ZIP_DEFLATED, compresslevel=9) as zf:
        for name in sorted(files):
            info = zipfile.ZipInfo(name, date_time=(1980, 1, 1, 0, 0, 0))
            info.compress_type = zipfile.ZIP_DEFLATED
            info.external_attr = 0o644 << 16
            zf.writestr(info, files[name])
    return buf.getvalue()


def now_rfc3339() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def build(
    content: dict,
    attachments: Iterable[Attachment] = (),
    *,
    generator: str = "ttt-cli/0.1.0",
    created: Optional[str] = None,
    flags: int = 0,
    major: int = 1,
    minor: int = 0,
) -> bytes:
    """组装一个 .ttt 文件的完整字节。"""
    if not isinstance(content, dict):
        raise TTTError("BAD_HEADER", "content 必须是 JSON 对象")
    if major not in SUPPORTED_MAJOR:
        raise TTTError("UNSUPPORTED_VERSION", "本实现只写 major=1，收到 %r" % major)
    if minor > SUPPORTED_MINOR:
        raise TTTError("UNSUPPORTED_VERSION", "本实现最高 minor=%d，收到 %r" % (SUPPORTED_MINOR, minor))

    files: Dict[str, bytes] = {}
    manifest_att: List[dict] = []
    for att in attachments:
        name = normalize_member_path(att.path)
        if name in files:
            raise TTTError("BAD_ATTACHMENT", "附件路径重复: %r" % name)
        files[name] = att.data
        manifest_att.append(
            {
                "path": name,
                "size": len(att.data),
                "sha256": hashlib.sha256(att.data).hexdigest(),
            }
        )
    manifest_att.sort(key=lambda item: item["path"])

    header = {
        "schema": "ttt/%d.%d" % (major, minor),
        "major": major,
        "minor": minor,
        "created": created or now_rfc3339(),
        "generator": generator,
        "content": content,
        "attachments": manifest_att,
    }
    raw_header = _canonical_json(header)
    if len(raw_header) > MAX_HEADER_JSON:
        raise TTTError("BAD_HEADER", "清单超过 %d 字节" % MAX_HEADER_JSON)

    payload = _zip_bytes(files)
    if len(payload) > MAX_PAYLOAD:
        raise TTTError("ZIP_LIMIT", "负载超过 %d 字节" % MAX_PAYLOAD)

    fixed = MAGIC + struct.pack(
        ">HHIIQ32s",
        major,
        minor,
        flags,
        len(raw_header),
        len(payload),
        hashlib.sha256(raw_header + payload).digest(),
    )
    return fixed + raw_header + payload


def parse(data: bytes) -> Document:
    """结构解析（不强制版本策略，便于 inspect 未知版本）。"""
    if len(data) < HEADER_SIZE:
        raise TTTError("TRUNCATED", "文件仅 %d 字节，不足 %d" % (len(data), HEADER_SIZE))
    magic, major, minor, flags, hlen, plen, digest = struct.unpack(
        ">4sHHIIQ32s", data[:HEADER_SIZE]
    )
    if magic != MAGIC:
        raise TTTError("BAD_MAGIC", "magic=%r，期望 %r" % (magic, MAGIC))
    if not 0 < hlen <= MAX_HEADER_JSON:
        raise TTTError("BAD_HEADER", "header_len=%r 越界" % hlen)
    if plen > MAX_PAYLOAD:
        raise TTTError("ZIP_LIMIT", "payload_len=%r 超过上限 %d" % (plen, MAX_PAYLOAD))
    total = HEADER_SIZE + hlen + plen
    if len(data) != total:
        raise TTTError("TRUNCATED", "实际长度 %d != 头部声明 %d" % (len(data), total))

    raw_header = data[HEADER_SIZE : HEADER_SIZE + hlen]
    payload = data[HEADER_SIZE + hlen :]
    if hashlib.sha256(raw_header + payload).digest() != digest:
        raise TTTError("BAD_SHA", "头部或负载 SHA-256 与固定头不一致")

    try:
        header = json.loads(raw_header.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise TTTError("BAD_HEADER", "清单 JSON 解析失败: %s" % exc) from exc
    if not isinstance(header, dict):
        raise TTTError("BAD_HEADER", "清单必须是 JSON 对象")

    warnings: List[str] = []
    if minor > SUPPORTED_MINOR:
        warnings.append("minor=%d 高于本实现支持的 %d，按尽力读取" % (minor, SUPPORTED_MINOR))
    unknown_flags = flags & ~KNOWN_FLAGS
    if unknown_flags:
        warnings.append("忽略未知 flags 位 0x%x" % unknown_flags)
    unknown_keys = sorted(set(header) - KNOWN_HEADER_KEYS)
    if unknown_keys:
        warnings.append("忽略未知清单字段: %s" % ", ".join(unknown_keys))

    return Document(major=major, minor=minor, flags=flags, header=header, payload=payload, warnings=warnings)


def _zip_infos(payload: bytes) -> Dict[str, zipfile.ZipInfo]:
    if not payload:
        return {}
    try:
        zf = zipfile.ZipFile(io.BytesIO(payload))
    except zipfile.BadZipFile as exc:
        raise TTTError("BAD_ATTACHMENT", "负载不是合法 ZIP: %s" % exc) from exc
    with zf:
        infos = zf.infolist()
        if len(infos) > MAX_ENTRIES:
            raise TTTError("ZIP_LIMIT", "条目数 %d 超过 %d" % (len(infos), MAX_ENTRIES))
        total_uncompressed = 0
        result: Dict[str, zipfile.ZipInfo] = {}
        for info in infos:
            name = normalize_member_path(info.filename)
            if name in result:
                raise TTTError("BAD_ATTACHMENT", "ZIP 条目重名: %r" % name)
            if info.is_dir():
                raise TTTError("UNSAFE_PATH", "不允许目录条目: %r" % name)
            mode = (info.external_attr >> 16) & 0o170000
            if mode == 0o120000:
                raise TTTError("UNSAFE_PATH", "不允许符号链接条目: %r" % name)
            total_uncompressed += info.file_size
            result[name] = info
        limit = min(MAX_UNCOMPRESSED, len(payload) * MAX_RATIO)
        if total_uncompressed > limit:
            raise TTTError("ZIP_LIMIT", "解压总大小 %d 超过上限 %d" % (total_uncompressed, limit))
    return result


def _check_header(doc: Document, infos: Dict[str, zipfile.ZipInfo], data_of) -> None:
    header = doc.header
    missing = sorted(REQUIRED_HEADER_KEYS - set(header))
    if missing:
        raise TTTError("BAD_HEADER", "缺少必填字段: %s" % ", ".join(missing))
    if not isinstance(header["schema"], str) or not header["schema"].startswith("ttt/"):
        raise TTTError("BAD_HEADER", "schema 非法: %r" % (header["schema"],))
    if header["major"] != doc.major or header["minor"] != doc.minor:
        raise TTTError("BAD_HEADER", "清单版本与固定头不一致")
    if not isinstance(header["created"], str) or not header["created"]:
        raise TTTError("BAD_HEADER", "created 必须是非空字符串")
    if not isinstance(header["generator"], str) or not header["generator"]:
        raise TTTError("BAD_HEADER", "generator 必须是非空字符串")
    if not isinstance(header["content"], dict):
        raise TTTError("BAD_HEADER", "content 必须是 JSON 对象")
    if not isinstance(header["attachments"], list):
        raise TTTError("BAD_HEADER", "attachments 必须是数组")

    declared: Dict[str, tuple] = {}
    for item in header["attachments"]:
        if not isinstance(item, dict) or not {"path", "size", "sha256"} <= set(item):
            raise TTTError("BAD_ATTACHMENT", "附件条目缺少 path/size/sha256: %r" % (item,))
        path = normalize_member_path(item["path"])
        if path in declared:
            raise TTTError("BAD_ATTACHMENT", "附件清单重复: %r" % path)
        if not isinstance(item["size"], int) or item["size"] < 0:
            raise TTTError("BAD_ATTACHMENT", "附件 size 非法: %r" % (item["size"],))
        if not isinstance(item["sha256"], str) or not _SHA_HEX.match(item["sha256"]):
            raise TTTError("BAD_ATTACHMENT", "附件 sha256 非法: %r" % (item["sha256"],))
        declared[path] = (item["size"], item["sha256"])

    if set(declared) != set(infos):
        extra = sorted(set(infos) - set(declared))
        lost = sorted(set(declared) - set(infos))
        raise TTTError(
            "BAD_ATTACHMENT",
            "清单与 ZIP 条目不一致（多出: %s；缺失: %s）" % (extra or "无", lost or "无"),
        )

    for path, (size, digest) in declared.items():
        info = infos[path]
        if info.file_size != size:
            raise TTTError("BAD_ATTACHMENT", "%r 大小不一致：清单 %d，实条目 %d" % (path, size, info.file_size))
        if hashlib.sha256(data_of(path)).hexdigest() != digest:
            raise TTTError("BAD_ATTACHMENT", "%r SHA-256 与清单不一致" % path)


def validate_document(doc: Document) -> Document:
    """按规范做完整校验；通过则原样返回 doc（含 warnings）。"""
    if doc.major not in SUPPORTED_MAJOR:
        raise TTTError("UNSUPPORTED_VERSION", "不支持的 major=%r" % (doc.major,))
    infos = _zip_infos(doc.payload)
    if doc.payload:
        with zipfile.ZipFile(io.BytesIO(doc.payload)) as zf:
            _check_header(doc, infos, lambda name: zf.read(name))
    elif doc.header.get("attachments"):
        raise TTTError("BAD_ATTACHMENT", "清单声明了附件但负载为空")
    else:
        _check_header(doc, infos, lambda name: b"")
    return doc


def validate(data: bytes) -> Document:
    return validate_document(parse(data))


def extract(data: bytes, dest: str, *, force: bool = False) -> List[str]:
    """校验后把附件安全解包到 dest，返回写出的相对路径。"""
    import os

    doc = validate(data)
    written: List[str] = []
    with zipfile.ZipFile(io.BytesIO(doc.payload)) as zf:
        for path in sorted(infos_names(doc)):
            target = os.path.join(dest, *path.split("/"))
            if os.path.exists(target) and not force:
                raise TTTError("IO_ERROR", "目标已存在（加 --force 覆盖）: %s" % target)
            parent = os.path.dirname(target)
            if parent:
                os.makedirs(parent, exist_ok=True)
            with open(target, "wb") as fh:
                fh.write(zf.read(path))
            written.append(path)
    return written


def infos_names(doc: Document) -> List[str]:
    return list(_zip_infos(doc.payload))
