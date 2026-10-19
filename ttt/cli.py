"""ttt 命令行：new / inspect / validate / extract。"""

from __future__ import annotations

import argparse
import json
import sys
import zipfile

from .format import (
    Attachment,
    TTTError,
    build,
    extract,
    parse,
    validate_document,
    now_rfc3339,
)

EXIT_USAGE = 2


def _read_bytes(path: str) -> bytes:
    try:
        with open(path, "rb") as fh:
            return fh.read()
    except OSError as exc:
        raise TTTError("IO_ERROR", "读取 %s 失败: %s" % (path, exc)) from exc


def _write_bytes(path: str, data: bytes) -> None:
    try:
        with open(path, "wb") as fh:
            fh.write(data)
    except OSError as exc:
        raise TTTError("IO_ERROR", "写入 %s 失败: %s" % (path, exc)) from exc


def _parse_tags(pairs) -> dict:
    out = {}
    for item in pairs or []:
        if "=" not in item:
            raise TTTError("BAD_HEADER", "--tag 需要 KEY=VALUE 形式: %r" % item)
        key, _, value = item.partition("=")
        if not key:
            raise TTTError("BAD_HEADER", "--tag 的 KEY 不能为空")
        out[key] = value
    return out


def _build_content(args) -> dict:
    content: dict = {}
    if args.content_json:
        try:
            loaded = json.loads(args.content_json)
        except json.JSONDecodeError as exc:
            raise TTTError("BAD_HEADER", "--content-json 不是合法 JSON: %s" % exc) from exc
        if not isinstance(loaded, dict):
            raise TTTError("BAD_HEADER", "--content-json 必须是 JSON 对象")
        content.update(loaded)
    if args.content:
        loaded = json.loads(_read_bytes(args.content).decode("utf-8"))
        if not isinstance(loaded, dict):
            raise TTTError("BAD_HEADER", "content 文件必须是 JSON 对象")
        content.update(loaded)
    content.update(_parse_tags(args.tag))
    return content


def cmd_new(args) -> int:
    content = _build_content(args)
    attachments = []
    for spec in args.attach or []:
        src, _, name = spec.partition(":")
        name = name or src.rsplit("/", 1)[-1]
        attachments.append(Attachment(path=name, data=_read_bytes(src)))
    data = build(
        content,
        attachments,
        generator=args.generator,
        created=args.created,
        minor=args.minor,
    )
    _write_bytes(args.output, data)
    print("%s  %d bytes  major=%d minor=%d" % (args.output, len(data), 1, args.minor))
    return 0


def cmd_inspect(args) -> int:
    doc = parse(_read_bytes(args.file))
    if args.json:
        payload = {"major": doc.major, "minor": doc.minor, "flags": doc.flags,
                   "header": doc.header, "warnings": doc.warnings}
        print(json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True))
        return 0
    header = doc.header
    print("file      : %s" % args.file)
    print("version   : %d.%d" % (doc.major, doc.minor))
    print("flags     : 0x%x" % doc.flags)
    print("schema    : %s" % header.get("schema"))
    print("created   : %s" % header.get("created"))
    print("generator : %s" % header.get("generator"))
    print("content   : %s" % json.dumps(header.get("content"), ensure_ascii=False, sort_keys=True)[:200])
    atts = header.get("attachments") or []
    print("attachments: %d" % len(atts))
    for item in atts:
        print("  - %s  %s bytes  %s" % (item.get("path"), item.get("size"), str(item.get("sha256"))[:12]))
    for warning in doc.warnings:
        print("warning   : %s" % warning)
    return 0


def cmd_validate(args) -> int:
    doc = validate_document(parse(_read_bytes(args.file)))
    if args.json:
        print(json.dumps({"ok": True, "major": doc.major, "minor": doc.minor,
                          "warnings": doc.warnings}, ensure_ascii=False))
    else:
        print("OK  %s  (%d.%d)" % (args.file, doc.major, doc.minor))
        for warning in doc.warnings:
            print("warning: %s" % warning)
    return 0


def cmd_extract(args) -> int:
    written = extract(_read_bytes(args.file), args.dir, force=args.force)
    for path in written:
        print(path)
    print("已解包 %d 个条目 → %s" % (len(written), args.dir))
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="ttt", description="TTT (.ttt) 容器工具")
    parser.add_argument("--version", action="version", version="ttt 0.1.0")
    sub = parser.add_subparsers(dest="command", required=True)

    p_new = sub.add_parser("new", help="生成一个 .ttt 文件")
    p_new.add_argument("-o", "--output", required=True, help="输出文件路径")
    p_new.add_argument("--content-json", help="content 的 JSON 字面量")
    p_new.add_argument("--content", help="content JSON 文件路径")
    p_new.add_argument("--tag", action="append", help="追加 KEY=VALUE 到 content（可重复）")
    p_new.add_argument("--attach", action="append", help="附件，SRC[:ZIP内路径]（可重复）")
    p_new.add_argument("--generator", default="ttt-cli/0.1.0")
    p_new.add_argument("--created", default=None, help="覆盖 created 时间戳（测试用）")
    p_new.add_argument("--minor", type=int, default=0)
    p_new.set_defaults(func=cmd_new)

    p_inspect = sub.add_parser("inspect", help="打印清单与结构（不做完整校验）")
    p_inspect.add_argument("file")
    p_inspect.add_argument("--json", action="store_true")
    p_inspect.set_defaults(func=cmd_inspect)

    p_validate = sub.add_parser("validate", help="完整校验")
    p_validate.add_argument("file")
    p_validate.add_argument("--json", action="store_true")
    p_validate.set_defaults(func=cmd_validate)

    p_extract = sub.add_parser("extract", help="校验并解包附件")
    p_extract.add_argument("file")
    p_extract.add_argument("-C", "--dir", default=".")
    p_extract.add_argument("--force", action="store_true")
    p_extract.set_defaults(func=cmd_extract)
    return parser


def main(argv=None) -> int:
    args = build_parser().parse_args(argv)
    try:
        return args.func(args)
    except TTTError as exc:
        print("ttt: %s: %s" % (exc.code, exc.message), file=sys.stderr)
        return EXIT_USAGE
    except zipfile.BadZipFile as exc:  # 兜底，正常路径已在 format 内转换
        print("ttt: BAD_ATTACHMENT: %s" % exc, file=sys.stderr)
        return EXIT_USAGE


if __name__ == "__main__":
    raise SystemExit(main())
