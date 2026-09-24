# Canonical compact source pipeline

Ouro keeps human-authored `.ouro` files unchanged. The checked compiler pipeline
feeds the lexer tokens directly to the parser after preprocessing:

```text
original source bytes
  -> import / record preprocessing
  -> existing lexer rules
  -> Token stream
  -> parser / elaborator / lowerer / checker / extraction
```

`compiler/driver.ouro`'s `lex_then_parse` helper also wraps tokens in
`CanonicalSourceUnit` for metadata and position mapping. This artifact is not a
new source format. Neither path requires serializing and reopening token bytes.

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

The parser reports positions in token-space. The `lex_then_parse` helper maps
these positions through `CanonicalSourceUnit`, not the optional serialized bytes.
The current self-hosted lexer ABI does not
yet expose byte start/end spans for each token; until that ABI grows spans, the
map stores stable original token-index spans and maps EOF/out-of-range positions
to the original source length.

Tools that need byte positions use `compiler/source_spans.ouro`, which the
compiler pipeline does not import. `lex_spanned` steps the production lexer and
records where each token starts and ends; `token_span_bytes` maps a token range
to byte offsets. `parse_spanned` is the production parser dispatcher with
`ESpan` token ranges around expressions. Every other `Expr` consumer treats
`ESpan` as transparent, and `strip_spans` returns the production tree. Positions
refer to the lexed text, so a tool must not report them against the original
file when import-alias or record preprocessing rewrote it. Clippy reports a
proof's range only in that unchanged case.
`tests/source_span_tests.ouro` checks agreement with the production lexer and
parser on inline cases and repository sources, and that each range parsed alone
yields its expression.

## Hashes and cache identity

`canonical_source.ouro` exposes two deterministic hash inputs:

- semantic bytes: token-derived compact representation with non-semantic trivia
  removed;
- tooling bytes: semantic bytes plus preserved `SourceDirective` metadata.

The hash is an identity/cache key, not a cryptographic trust boundary. A future
cache can use the semantic hash only for work proven independent of ordinary
comments and formatting; tooling caches need the metadata-bearing or raw-source
hash as appropriate. These policies remain distinct.

## Materialization

Release toolchains select a compact final bootstrap stage:

```sh
python3 scripts/ouro_build.py build --compact-sources
```

The [bootstrap driver](build.md#c-bootstrap) keeps its original snapshot `o/`
and writes a separate `compact/` tree inside the private build attempt.
`scripts/compact_source.py` removes ordinary comments, blank lines, indentation,
and repeated whitespace. It preserves literal bytes, `-- @...` directives,
token separators, relative module paths, and line breaks between surviving source
lines. It does not use the token serializer, whose output omits directives.

The bridge builds P1 from original sources. P1 strictly checks both original and
compact compiler and acceptance roots, runs the ABI laws on compact sources, and
emits P2 from the compact tree. The complete generated frontend and backend C must
match P1; the existing P2 positive and exact negative behavior checks still run.
Compaction adds no program-acceptance authority to the host script.

The build key includes the compaction mode and helper contents. `inputs.json`
records both trees' hashes and per-file byte counts; frozen inputs are rechecked
before each bootstrap command. Release jobs upload it with `report.json` and
the installed compiler receipt as `bootstrap-evidence-<platform>` artifacts.
Archives retain the original readable sources. Diagnostics during the compact
stage refer to that private copy, whose line numbers can differ from the original.
Plain `build` and `rebuild` keep the original-source path; both accept the flag.

## Regression checks

Host materialization and bootstrap ordering regressions run through
`python3 scripts/bootstrap_compiler_test.py`. Focused Ouro-native checks live in
`tests/canonical.ouro` and cover
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
