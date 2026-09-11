# Canonical compact source pipeline

Ouro keeps human-authored `.ouro` files unchanged. Semantic compilation now has
an explicit internal source boundary after preprocessing and lexing:

```text
original source bytes
  -> existing lexer rules
  -> Token stream
  -> CanonicalSourceUnit
  -> parser / elaborator / lowerer / checker / extraction
```

`CanonicalSourceUnit` is a compiler artifact, not a new source format. The hot
path does not write a minified file, reopen it, or lex it again. The parser keeps
consuming the token stream that the lexer already produced.

## Removed trivia

The existing lexer owns lexical semantics. Whitespace, blank lines, CRLF/LF
layout trivia, ordinary `--` comments, and formatting-only spacing do not become
parser input. The canonical stage makes that boundary explicit and exposes the
compact semantic token representation to later frontend stages.

The canonical serializer can materialize inspection bytes from tokens on demand,
for example `def x:Type:=1`, but this is optional debug/cache evidence. It is
not required by compilation.

## Preserved metadata

Comments whose trimmed line-comment body begins with `@` are preserved as
`SourceDirective` metadata with their original source offsets. This keeps current
repository directives such as `@entry`, `@export`, `@doc`, `@bound`, and similar
future policy/tooling markers out of the semantic token stream without losing
that signal.

Documentation comments and prose comments are not copied into the semantic
artifact. Source-aware tools that need comments, such as formatter, LSP,
analyzer, fixer, and documentation tooling, remain on the original-source side
of the boundary.

## Source mapping

The parser reports positions in token-space. Compilation errors now flow through
`CanonicalSourceUnit` instead of optional compact bytes, so diagnostics do not
refer to the serialized compact form. The current self-hosted lexer ABI does not
yet expose byte start/end spans for each token; until that ABI grows spans, the
map stores stable original token-index spans and maps EOF/out-of-range positions
to the original source length.

This is intentionally a fail-closed migration seam: there is no silent fallback
from canonical compilation back to a separate original-source parse.

## Hashes and cache identity

`canonical_source.ouro` exposes two deterministic hash inputs:

- semantic bytes: token-derived compact representation with non-semantic trivia
  removed;
- tooling bytes: semantic bytes plus preserved `SourceDirective` metadata.

The hash is an identity/cache key, not a cryptographic trust boundary. A future
cache can use the semantic hash for compilation work that is proven independent
of ordinary comments and formatting, while tooling caches should include the
metadata-bearing hash or the raw source hash as needed. This PR deliberately does
not collapse those cache policies into one key.

## Materialization

No compact source tree is required by the compiler path. If a host command later
adds materialization, it must write only under the controlled build directory
such as `_build/canonical/`, preserve relative module structure safely, validate
hashes, and never treat stale files as fresh compiler input.

## Regression checks

Focused Ouro-native checks live in `tests/canonical.ouro` and cover
compact byte serialization, token-boundary separators, string content containing
`--`, directive preservation, deterministic hashing, original-position mapping,
and removed-byte metrics on a small fixture.

Useful local checks:

```sh
sh scripts/ouro1.sh check tests/canonical.ouro
sh scripts/ouro1.sh check std/io.ouro
sh scripts/ouro1.sh fmt --check std/io.ouro
python3 scripts/bench_suite.py --out _build/bench-canonical
```

The benchmark suite records local wall-clock evidence only; do not claim a
performance improvement until before/after runs exist on the same machine.
