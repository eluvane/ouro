#!/usr/bin/env python3
"""Conservative source compaction for the checked release bootstrap.

This removes trivia, not tokens. Ouro still owns source acceptance; bootstrap
checks both source forms and requires equality of their complete generated C.
"""
from __future__ import annotations

KIND = "ouro.compact-source.v1"


def compact_source(source: bytes) -> bytes:
    """Keep literal bytes, directive comments and existing line boundaries."""
    output = bytearray()
    pending = b""
    index = 0
    identifier = False
    while index < len(source):
        byte = source[index]
        if byte in b" \t\r\n":
            pending = b"\n" if byte == 10 or pending == b"\n" else b" "
            index += 1
            identifier = False
            continue
        if source.startswith(b"--", index):
            end = source.find(b"\n", index)
            end = len(source) if end < 0 else end
            comment = source[index:end]
            if comment[2:].lstrip(b" \t\r").startswith(b"@"):
                if output:
                    output.extend(pending)
                output.extend(comment)
                pending = b""
            index = end
            identifier = False
            continue
        if output:
            output.extend(pending)
        pending = b""
        start = index
        index += 1
        if source.startswith(b'r#"', start):
            close = source.find(b'"#', start + 3)
            if close < 0:
                raise ValueError(f"COMPACT_SOURCE: unterminated raw string at byte {start}")
            index = close + 2
        elif byte == 34 or (byte == 39 and not identifier):
            while index < len(source) and source[index] != byte:
                index += 2 if source[index] == 92 else 1
            if index >= len(source):
                raise ValueError(f"COMPACT_SOURCE: unterminated string at byte {start}")
            index += 1
        identifier = (index == start + 1 and (65 <= byte <= 90 or 97 <= byte <= 122
                      or 48 <= byte <= 57 or byte in (95, 39)))
        output.extend(source[start:index])
    return bytes(output) + (b"\n" if output else b"")
