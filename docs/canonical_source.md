# Canonical compact source pipeline

The checked compiler path preprocesses `.ouro` source in memory and passes
the resulting token stream directly to the parser. Source files stay in
place.

```text
original source bytes
  -> import and record preprocessing
  -> lexer
  -> token stream
  -> parser, elaboration, lowering, and checking
```

The syntax-only `lex_then_parse` helper passes its input directly to the
lexer. It wraps the tokens in a `CanonicalSourceUnit` to retain token
positions and directive metadata.
Both paths use tokens as parser input. Compact byte serialization is optional.
[Source driver](../compiler/driver.ouro)

## Removed trivia

The lexer owns lexical semantics. It discards whitespace, blank lines, CRLF/LF
layout trivia, and ordinary `--` comments outside literals.

The canonical serializer can materialize inspection bytes from tokens on demand,
for example `def x:Type:=1`, but this is optional debug/cache evidence. It is
not required by compilation.

## Preserved metadata

`CanonicalSourceUnit` records line comments whose trimmed body begins with `@`
as `SourceDirective` metadata at their byte offsets in the lexical input.
Directives such as `@entry`, `@export`, `@doc`, and `@bound` stay outside the
semantic token stream.

Documentation comments and prose comments are not copied into the semantic
artifact. Source-aware tools that need comments, such as formatter, LSP,
analyzer, fixer, and documentation tooling, remain on the original-source side
of the boundary.

## Source mapping

The parser reports token positions. The `CanonicalSourceUnit` map retains
token ordinals, including the in-range EOF token. If a position is beyond the
map, `canonical_original_position` returns the byte length of the lexical
input. Use the byte-span helpers for byte ranges within the input.
[Canonical source model](../compiler/canonical_model.ouro)

The byte-span helpers in [`source_spans.ouro`](../compiler/source_spans.ouro)
step the production lexer and mark token boundaries. `token_span_bytes`
maps a token range to offsets in the lexed text. Tools can use `parse_spanned`
to record expression ranges as `ESpan` nodes and `strip_spans` to recover the
ordinary tree.

`compile_checked_units_with_source_origins` also records token boundaries.
Its occurrence capture uses a checked map to project ranges onto the original
source when an original envelope is available. A consumer with offsets into
preprocessed text alone must use that text. Clippy reports a proof range
only when its lexed text matches the original.
Alias qualification keeps the same source byte length when replacing `.` with
the internal marker, and masked `as` / `open` syntax keeps line endings. This
does not by itself provide original byte spans for rewritten tokens; tools
still follow the mapping limit above. Raw source containing the internal
marker is rejected before the checked parser can consume it.
`tests/source_span_tests.ouro` checks agreement with the production lexer and
parser on inline cases and repository sources, and that each range parsed alone
yields its expression.

## Hashes and cache identity

`canonical_bytes_from` serializes the tokens without directives or ordinary
trivia. `canonical_semantic_hash_from` hashes those bytes. Tools can read
directives separately with `canonical_directives`.
[Token serialization and hashing](../compiler/canonical_source.ouro) ·
[Directive access](../compiler/canonical_model.ouro)

Use the semantic hash as a cache identity only for work independent of omitted
source data. A cache for source-aware tooling must include the metadata or
raw source it depends on. Keep trust checks independent of the semantic hash.

## Materialization

Release builds emit the final bootstrap stage from a checked compact source
tree. To reproduce this mode, meet the build requirements and run the command
from the repository root in a POSIX-compatible shell. The build writes outputs
under `_build/` by default and reports `BUILD: OK` on success.
[Build requirements](getting_started.md#requirements)

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

From the repository root, run the Python checks for host-side materialization
and bootstrap ordering. A passing run exits with status zero.

```sh
python3 scripts/bootstrap_compiler_test.py
```

Run the compiler-checking suite under the same build prerequisites to execute
the `canonical source smoke behavior` assertion in `compiler_structural`. Its
fixture checks compact serialization, token separators, string content
containing `--`, directive preservation, deterministic hashing, token-position
mapping, and removed-byte counts. Look for a passing `compiler_structural`
result in the suite report.
[Canonical fixture](../tests/canonical.ouro) ·
[Structural test](../tests/compiler_structural_tests.ouro) ·
[Compiler-checking commands](ci.md#validation-matrix)
