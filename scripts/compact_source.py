#!/usr/bin/env python3
"""Conservative source compaction for the checked release bootstrap.

This removes trivia, not tokens. Ouro still owns source acceptance; bootstrap
checks both source forms and requires equality of their complete generated C.
"""
from __future__ import annotations

KIND = "ouro.compact-source.v1"


def _multiline_end(source: bytes, start: int) -> int:
    body = start + 3
    if source.startswith(b"\r\n", body):
        line = body + 2
    elif source.startswith(b"\n", body):
        line = body + 1
    else:
        raise ValueError(f"COMPACT_SOURCE: malformed multiline string at byte {start}")
    while line < len(source):
        quote = line
        while quote < len(source) and source[quote] in b" \t":
            quote += 1
        if source.startswith(b'"""', quote):
            return quote + 3
        next_line = source.find(b"\n", line)
        if next_line < 0:
            break
        line = next_line + 1
    raise ValueError(f"COMPACT_SOURCE: unterminated multiline string at byte {start}")


def compact_source(source: bytes) -> bytes:
    """Keep literal bytes, directive comments and existing line boundaries."""
    output = bytearray()
    pending = b""
    index = 0
    while index < len(source):
        byte = source[index]
        if byte in b" \t\r\n":
            pending = b"\n" if byte == 10 or pending == b"\n" else b" "
            index += 1
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
            continue
        if output:
            output.extend(pending)
        pending = b""
        start = index
        index += 1
        if source.startswith(b'"""', start):
            index = _multiline_end(source, start)
        elif source.startswith(b'r#"', start):
            close = source.find(b'"#', start + 3)
            if close < 0:
                raise ValueError(f"COMPACT_SOURCE: unterminated raw string at byte {start}")
            index = close + 2
        elif byte == 34:
            while index < len(source) and source[index] != 34:
                index += 2 if source[index] == 92 else 1
            if index >= len(source):
                raise ValueError(f"COMPACT_SOURCE: unterminated string at byte {start}")
            index += 1
        output.extend(source[start:index])
    return bytes(output) + (b"\n" if output else b"")
