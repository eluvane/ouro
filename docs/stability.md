# Stability and compatibility

Ouro is pre-1.0 research software. Check these compatibility rules before
upgrading code, package files, or tool automation.

## Versioning

Release tags and shared version files are defined in [Releasing](releasing.md#version).

During the `0.x` series, breaking changes are allowed. A breaking user-visible
change must be documented in its canonical page, covered by tests or fixtures, and
accompanied by migration guidance. A substantial language or trust-boundary
change also needs an RFC.

## Current promises

| Surface | Pre-1.0 policy |
| --- | --- |
| Kernel/core acceptance | Changes are deliberate, tested against valid and invalid corpora, and documented with the trust boundary. |
| Surface syntax and semantics | May evolve; examples, diagnostics, formatter behavior, and docs move with the change. |
| Standard library | Module names and signatures may change; generated API pages and samples are updated together. |
| CLI and tools | Commands may evolve. The [focused validation suites](ci.md#validation-matrix) cover tool behavior. The [documentation gate](ci.md#documentation-and-repository-checks) covers repository paths, links, and selected examples. |
| Diagnostic codes | Stable codes are preferred within a release line; replacements are recorded when a code changes. |
| Package files | `Ouro.seal` and `Ouro.lock` are experimental and may require migration. |
| Core artifact schema | A breaking encoding receives a new version identifier rather than silent reinterpretation. |
| Generated bootstrap artifacts | Internal implementation inputs, not a user API. |

## What counts as breaking

A change is breaking when it alters how existing code or automation is
accepted, evaluated, imported, packaged, or invoked. Diagnostic codes and
trusted components are also part of this policy.

## Experimental areas

The following areas are especially likely to change before 1.0:

- effect-handler syntax and semantics;
- package and registry conventions;
- LSP behavior and editor integration;
- runtime and IO breadth;
- module and import ergonomics;
- self-hosting and bootstrap artifacts;
- generated-development and synthesis interfaces.

## Import migration

An alias identifies the file named in its import. If older code used an
alias to reach a transitive declaration, import the declaring file directly
and use its alias. Qualify a bare name that becomes ambiguous after adding
an import to an aliased graph. A graph of plain imports still rejects
colliding public declarations.

The compiler reserves `private` as a declaration modifier. Rename any binder
or declaration named `private` in older code before upgrading. Scoped local
opens and private declarations are supported. Selective imports and
visibility remain pre-1.0 surfaces. The [module syntax reference](syntax.md#modules-and-imports)
describes supported forms. [RFC 0004](rfc/0004-module-identity.md) remains
proposed.

## Assurance is separate from compatibility

Compatibility describes whether an interface stays the same. The
[trusted computing base](tcb.md#assurance-limits) states what compiler checking
does and does not establish.
