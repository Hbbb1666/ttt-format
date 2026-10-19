"""TTT v0.1 单元测试（unittest，兼容 pytest 直接收集）。"""

from __future__ import annotations

import hashlib
import io
import json
import os
import struct
import tempfile
import unittest
import zipfile

from ttt.cli import main as cli_main
from ttt.format import (
    MAGIC,
    Attachment,
    TTTError,
    build,
    extract,
    parse,
    validate,
)

BASE_HEADER = {
    "schema": "ttt/1.0",
    "major": 1,
    "minor": 0,
    "created": "2026-01-01T00:00:00Z",
    "generator": "test/0",
    "content": {"tag": "demo"},
    "attachments": [],
}


def wrap(header: dict, payload: bytes, *, major: int = 1, minor: int = 0, flags: int = 0) -> bytes:
    """手工拼一个 .ttt（绕过 build，用于构造畸形样本）。"""
    raw = json.dumps(header, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")
    fixed = MAGIC + struct.pack(
        ">HHIIQ32s", major, minor, flags, len(raw), len(payload), hashlib.sha256(raw + payload).digest()
    )
    return fixed + raw + payload


def zip_bytes(files: dict, *, symlink: bool = False, raw_name: bool = False) -> bytes:
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", compression=zipfile.ZIP_DEFLATED) as zf:
        for name, data in files.items():
            if raw_name:
                zf.writestr(name, data)
                continue
            info = zipfile.ZipInfo(name, date_time=(1980, 1, 1, 0, 0, 0))
            info.external_attr = (0o120777 if symlink else 0o644) << 16
            zf.writestr(info, data)
    return buf.getvalue()


def attachment_entry(name: str, data: bytes) -> dict:
    return {"path": name, "size": len(data), "sha256": hashlib.sha256(data).hexdigest()}


class RoundTripTest(unittest.TestCase):
    def test_build_parse_validate(self):
        data = build({"tag": "demo"}, [Attachment("files/a.txt", b"hello")], created="2026-01-01T00:00:00Z")
        doc = validate(data)
        self.assertEqual(doc.major, 1)
        self.assertEqual(doc.header["content"], {"tag": "demo"})
        self.assertEqual(doc.header["attachments"][0]["path"], "files/a.txt")

    def test_deterministic(self):
        one = build({"a": 1}, [], created="2026-01-01T00:00:00Z", generator="test/0")
        two = build({"a": 1}, [], created="2026-01-01T00:00:00Z", generator="test/0")
        self.assertEqual(one, two)

    def test_empty_payload_ok(self):
        doc = validate(build({}, []))
        self.assertEqual(doc.header["attachments"], [])

    def test_extract_writes_files(self):
        data = build({"tag": "x"}, [Attachment("files/b.bin", b"\x00\x01"), Attachment("files/a.txt", b"hi")])
        with tempfile.TemporaryDirectory() as tmp:
            written = extract(data, tmp)
            self.assertEqual(sorted(written), ["files/a.txt", "files/b.bin"])
            with open(os.path.join(tmp, "files", "b.bin"), "rb") as fh:
                self.assertEqual(fh.read(), b"\x00\x01")


class HeaderErrorTest(unittest.TestCase):
    def test_bad_magic(self):
        good = build({}, [])
        with self.assertRaises(TTTError) as ctx:
            parse(b"XXXX" + good[4:])
        self.assertEqual(ctx.exception.code, "BAD_MAGIC")

    def test_truncated(self):
        good = build({}, [])
        with self.assertRaises(TTTError) as ctx:
            parse(good[:-1])
        self.assertEqual(ctx.exception.code, "TRUNCATED")

    def test_too_short(self):
        with self.assertRaises(TTTError) as ctx:
            parse(b"TTT1")
        self.assertEqual(ctx.exception.code, "TRUNCATED")

    def test_sha_tamper(self):
        good = bytearray(build({"tag": "demo"}, []))
        good[-1] ^= 0xFF
        with self.assertRaises(TTTError) as ctx:
            parse(bytes(good))
        self.assertEqual(ctx.exception.code, "BAD_SHA")

    def test_header_tamper(self):
        good = bytearray(build({"tag": "demo"}, []))
        idx = good.find(b'"demo"')
        self.assertGreater(idx, 0)
        good[idx + 1] = ord("X")  # "demo" -> "Xemo"，JSON 仍合法
        with self.assertRaises(TTTError) as ctx:
            parse(bytes(good))
        self.assertEqual(ctx.exception.code, "BAD_SHA")

    def test_bad_json(self):
        payload = b""
        raw = b"{not json"
        fixed = MAGIC + struct.pack(">HHIIQ32s", 1, 0, 0, len(raw), 0, hashlib.sha256(raw + payload).digest())
        with self.assertRaises(TTTError) as ctx:
            parse(fixed + raw)
        self.assertEqual(ctx.exception.code, "BAD_HEADER")

    def test_unsupported_major(self):
        data = wrap(BASE_HEADER, b"", major=2)
        with self.assertRaises(TTTError) as ctx:
            validate(data)
        self.assertEqual(ctx.exception.code, "UNSUPPORTED_VERSION")

    def test_higher_minor_warns(self):
        header = dict(BASE_HEADER, minor=3, schema="ttt/1.3")
        data = wrap(header, b"", minor=3)
        doc = validate(data)
        self.assertTrue(any("minor" in w for w in doc.warnings))

    def test_unknown_fields_warn(self):
        header = dict(BASE_HEADER, extra_field=1)
        data = wrap(header, b"", flags=0b10)
        doc = validate(data)
        self.assertTrue(any("extra_field" in w for w in doc.warnings))

    def test_missing_header_field(self):
        header = dict(BASE_HEADER)
        header.pop("generator")
        with self.assertRaises(TTTError) as ctx:
            validate(wrap(header, b""))
        self.assertEqual(ctx.exception.code, "BAD_HEADER")

    def test_content_must_be_object(self):
        header = dict(BASE_HEADER, content=[1, 2])
        with self.assertRaises(TTTError) as ctx:
            validate(wrap(header, b""))
        self.assertEqual(ctx.exception.code, "BAD_HEADER")


class PathSafetyTest(unittest.TestCase):
    def test_build_rejects_traversal(self):
        with self.assertRaises(TTTError) as ctx:
            build({}, [Attachment("../evil", b"x")])
        self.assertEqual(ctx.exception.code, "UNSAFE_PATH")

    def test_build_rejects_absolute(self):
        with self.assertRaises(TTTError):
            build({}, [Attachment("/etc/passwd", b"x")])

    def test_zip_traversal_entry(self):
        payload = zip_bytes({"../evil.txt": b"x"}, raw_name=True)
        header = dict(BASE_HEADER, attachments=[attachment_entry("ok.txt", b"y")])
        with self.assertRaises(TTTError) as ctx:
            validate(wrap(header, payload))
        self.assertEqual(ctx.exception.code, "UNSAFE_PATH")

    def test_symlink_entry(self):
        payload = zip_bytes({"link": b"target"}, symlink=True)
        header = dict(BASE_HEADER, attachments=[attachment_entry("link", b"target")])
        with self.assertRaises(TTTError) as ctx:
            validate(wrap(header, payload))
        self.assertEqual(ctx.exception.code, "UNSAFE_PATH")

    def test_directory_entry(self):
        buf = io.BytesIO()
        with zipfile.ZipFile(buf, "w") as zf:
            zf.writestr(zipfile.ZipInfo("dir/"), b"")
        header = dict(BASE_HEADER, attachments=[])
        with self.assertRaises(TTTError) as ctx:
            validate(wrap(header, buf.getvalue()))
        self.assertIn(ctx.exception.code, {"UNSAFE_PATH", "ZIP_LIMIT"})


class AttachmentTest(unittest.TestCase):
    def test_size_mismatch(self):
        payload = zip_bytes({"a.txt": b"1234"})
        header = dict(BASE_HEADER, attachments=[{"path": "a.txt", "size": 3, "sha256": hashlib.sha256(b"1234").hexdigest()}])
        with self.assertRaises(TTTError) as ctx:
            validate(wrap(header, payload))
        self.assertEqual(ctx.exception.code, "BAD_ATTACHMENT")

    def test_hash_mismatch(self):
        payload = zip_bytes({"a.txt": b"1234"})
        header = dict(BASE_HEADER, attachments=[{"path": "a.txt", "size": 4, "sha256": "0" * 64}])
        with self.assertRaises(TTTError) as ctx:
            validate(wrap(header, payload))
        self.assertEqual(ctx.exception.code, "BAD_ATTACHMENT")

    def test_extra_entry(self):
        payload = zip_bytes({"a.txt": b"1", "b.txt": b"2"})
        header = dict(BASE_HEADER, attachments=[attachment_entry("a.txt", b"1")])
        with self.assertRaises(TTTError) as ctx:
            validate(wrap(header, payload))
        self.assertEqual(ctx.exception.code, "BAD_ATTACHMENT")

    def test_missing_entry(self):
        payload = zip_bytes({"a.txt": b"1"})
        header = dict(BASE_HEADER, attachments=[attachment_entry("a.txt", b"1"), attachment_entry("b.txt", b"2")])
        with self.assertRaises(TTTError) as ctx:
            validate(wrap(header, payload))
        self.assertEqual(ctx.exception.code, "BAD_ATTACHMENT")

    def test_declared_attachment_with_empty_payload(self):
        header = dict(BASE_HEADER, attachments=[attachment_entry("a.txt", b"1")])
        with self.assertRaises(TTTError) as ctx:
            validate(wrap(header, b""))
        self.assertEqual(ctx.exception.code, "BAD_ATTACHMENT")

    def test_entry_count_limit(self):
        buf = io.BytesIO()
        with zipfile.ZipFile(buf, "w", compression=zipfile.ZIP_STORED) as zf:
            for i in range(10001):
                zf.writestr(zipfile.ZipInfo("f%05d" % i), b"")
        with self.assertRaises(TTTError) as ctx:
            validate(wrap(BASE_HEADER, buf.getvalue()))
        self.assertEqual(ctx.exception.code, "ZIP_LIMIT")


class CliTest(unittest.TestCase):
    def test_end_to_end(self):
        with tempfile.TemporaryDirectory() as tmp:
            out = os.path.join(tmp, "demo.ttt")
            self.assertEqual(cli_main(["new", "-o", out, "--tag", "demo=1"]), 0)
            self.assertEqual(cli_main(["validate", out]), 0)
            self.assertEqual(cli_main(["inspect", out, "--json"]), 0)
            self.assertEqual(cli_main(["extract", out, "-C", os.path.join(tmp, "out")]), 0)

    def test_bad_input_exit_code(self):
        with tempfile.TemporaryDirectory() as tmp:
            bad = os.path.join(tmp, "bad.ttt")
            with open(bad, "wb") as fh:
                fh.write(b"TTT1garbage")
            self.assertEqual(cli_main(["validate", bad]), 2)


if __name__ == "__main__":
    unittest.main()
