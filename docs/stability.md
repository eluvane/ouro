# Stability and compatibility

Ouro is pre-1.0 research software. The project is still refining the language,
runtime, package model, tooling, and bootstrap path, so compatibility is
narrower than it will be for a stable release.

## Versioning

Release tags and shared version files are defined in [Releasing](releasing.md#version).

During the `0.x` series, breaking changes are allowed. A breaking user-visible
change must be documented in `CHANGELOG.md`, covered by tests or fixtures, and
accompanied by migration guidance. A substantial language or trust-boundary
change also needs an RFC.

## Current promises

| Surface | Pre-1.0 policy |
| --- | --- |
| Kernel/core acceptance | Changes are deliberate, tested against valid and invalid corpora, and documented with the trust boundary. |
| Surface syntax and semantics | May evolve; examples, diagnostics, formatter behavior, and docs move with the change. |
| Standard library | Module names and signatures may change; generated API pages and samples are updated together. |
| CLI and tools | Commands may evolve, but documented commands are checked by repository gates. |
| Diagnostic codes | Stable codes are preferred within a release line; replacements are recorded when a code changes. |
| Package files | `Ouro.seal` and `Ouro.lock` are experimental and may require migration. |
| Core artifact schema | A breaking encoding receives a new version identifier rather than silent reinterpretation. |
| Generated bootstrap artifacts | Internal implementation inputs, not a user API. |

## What counts as breaking

A change is breaking when existing Ouro code or automation can be accepted,
rejected, evaluated, imported, packaged, or invoked differently. That includes
the surfaces in the table above, including diagnostic codes and trusted
components.

## Experimental areas

The following areas are especially likely to change before 1.0:

- effect-handler syntax and semantics;
- package and registry conventions;
- LSP behavior and editor integration;
- runtime and IO breadth;
- module and import ergonomics;
- self-hosting and bootstrap artifacts;
- generated-development and synthesis interfaces.

Import aliases identify the directly imported file. If a new import makes a
bare name ambiguous in an aliased graph, qualify the use with an alias. A
plain-only graph still rejects duplicate declarations. Code that used one alias
to reach another file's transitive declaration needs a direct import of that
file. Scoped local opens, selective imports, and visibility remain experimental
design work; see [module syntax](syntax.md#modules-and-imports).

## Assurance is separate from compatibility

Compatibility describes whether an interface stays the same. The
[trusted computing base](tcb.md#assurance-limits) states what compiler checking
does and does not establish.
