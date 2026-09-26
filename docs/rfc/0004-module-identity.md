# RFC 0004: Source module identity and import names

- Status: proposed
- Authors: Ouro contributors
- Created: 2026-09-26
- Supersedes: none
- Superseded by: none

## Summary

Resolve imported names against the canonical source unit that declares them.
An alias in `import "path.ouro" as A` names that unit within the importing file;
`A.member` selects one of its direct declarations. Plain imports continue to
make declarations available by their short names when lookup is unique.

## Motivation

Previously the import prepass removed aliases and qualification before parsing.
The resolver then flattened all imported declarations. Two distinct modules
declaring `value` cannot both be used through `A.value` and `B.value`, and a
qualified spelling can accidentally refer to a name from another import.
Adding an import must not silently change the declaration selected by an
existing short name.

## Proposal

The normalized source path identifies a module. The compiler records the
owning path of every declaration, including generated record constructors and
accessors where their generated names are unique. An import alias is local to
the file containing its import and binds
to the canonical path. Repeating a path through equivalent spellings or through
several imports does not create a second declaration identity.
Supplying two distinct source units under the same normalized path is an error;
the compiler must not select one body by input order.

`A.member` searches direct declarations of the module bound to `A`. It never
falls back to the flattened import closure. An unknown direct member is a
diagnostic; an unbound dotted prefix remains an invalid record projection.
A bare reference first uses a local term binder, then a declaration owned by
the current unit. Otherwise, a unique declaration in the imported closure is
available by its short name; distinct imported owners make that name ambiguous.
In `A.member`, the alias is a
qualification token; a same-spelled local binder does not redirect that
reference. The scoped-open implementation resolves `open A in expression` against
the same direct-owner registry inside its expression subtree. A lexical term
binder and a current-file declaration still take precedence over an open;
among opens, the innermost selection wins.
A direct import is required to qualify a transitive dependency.

`import "a.ouro" as A exposing (value as chosen, TypeName,)` selects direct
declarations of that file. The optional `as` in an item changes only its
unqualified and local-open name: `chosen` and `open A in chosen` resolve to
the selected declaration, while `A.value` keeps its original member name.
`A.chosen` is not introduced. `exposing ()` grants no names. Repeated imports
of one canonical file must use the same selector clause. A selected original
name must be directly declared by the target; selection cannot import a
transitive name. Plain import edges inherit the target file's effective
exported bindings, including renamed names from a selective edge. Selectors
belong to each importing file and never form a graph-wide union. An
independent unrestricted path can expose a declaration hidden on another path.

Lookup remains lexical binder, current-file declaration, innermost open,
outer opens, then unique imported name. A local open uses the selected local
names of its direct alias target; qualified references use selected original
names. Ambiguous visible bindings are rejected before selecting any by import
order. Every imported declaration receives its own internal identity when a
selective edge is reached, so a hidden bare name cannot keep a flattened
identifier accidentally. Generated record references require an exact
compiler-issued marker, record owner, and member grant; the grant only resolves
when that symbol is visible through the importing file's effective scope.

Name resolution runs before lowering and emits unique internal identities for
distinct declarations. It does not discard imports, declarations, or bodies.
The existing compiler-owned declaration checker still receives the complete
ordered import closure and decides acceptance. Missing units, cycles, name
resolution exhaustion, and malformed source remain typed failures.

Identity rewriting activates when the reached graph has an alias or selective
edge. Plain-only graphs retain the existing duplicate-declaration error for
collisions. Private declarations, re-exports, and two same-named record
declarations remain subsequent contracts; record generation still uses a
shared registry before declaration ownership is assigned.

## Compatibility and migration

Existing plain imports with unique short names keep their spelling. Code that
relied on `A.member` to find a declaration from another imported file must
import that file directly and use its own alias. A new colliding import turns an
unqualified reference with no current-unit declaration into an ambiguity
diagnostic; qualify the reference.
Selective imports restrict names, including constructor and accessor names;
select all needed direct members or use an unrestricted import. An alias can
still qualify only selected members under their original spelling. The full
import closure remains checked. Tooling that merely harvests import paths does
not become an acceptance authority for selector semantics.
Colliding `IO`, `io_bind`, or `pure` wrapper names currently report ambiguity
even when qualified. Their lowering uses a single legacy operation slot; this
implementation does not choose one imported wrapper by spelling. String and
represented List/Unit literal hints instead use intrinsic and representation
role declarations, with the checker validating those roles before acceptance.
The formatter, dependency scanners, package tooling, diagnostics, and
source-span mapping need their existing gates before release. The alias and
open prepass preserves source length and line endings when it masks syntax;
the record prepass has its own source mapping contract.

## Trust and security

The compiler frontend owns module identity and name resolution. This proposal
adds no IO, network, process, or checker dependency. It does not
expand the pure checker allowlist. Every reached imported body remains in the
checker input, including bodies that no source reference uses. Source rewrites
or analyzer facts alone cannot authorize a declaration.

## Alternatives

Textually removing `A.` retains the existing collision and foreign-member
problems. Accepting the first short-name match makes behavior depend on import
order. Rejecting all collisions prevents two libraries with the same short
name from being used together. A canonical module-and-declaration identity
allows explicit disambiguation while preserving ordinary imports.

## Validation

Compiler fixtures need distinct modules with the same short name, qualified
selection of both, rejected ambiguous bare use, rejected unknown alias and
member, direct versus transitive qualification, and path normalization.
Fixtures must cover local binder and record-projection collisions, file-local
alias scope, generated record declarations, cycles, and an invalid imported
body that remains rejected when unused. Selective fixtures need local renames,
empty clauses, hidden bare/qualified/open/constructor/accessor references,
cross-file selectors, transitive plain inheritance, and an independent plain
path. Parser/source-span, formatter,
dependency-tool, package, and checker suites must preserve their existing
gates. Stage-loop evidence is required before any generated bootstrap update.

## Documentation

Update `docs/syntax.md`, `docs/architecture.md`, `docs/language/ergonomic-syntax.md`,
`docs/tcb.md` if the described trust boundary changes, and `CHANGELOG.md`.

## Diagnostics and remaining design

The first implementation uses errors 95 for a missing direct member, 96 for
an ambiguous imported short name, 97 for resolution fuel exhaustion, and 98
for a malformed name mapping or a qualified marker in a declaration or binder.
Raw marker input is a lexical error 11; an unknown dotted prefix follows the
existing record-projection error 77. The broader privacy and re-export
contract remains proposed, not maintainer-accepted.
