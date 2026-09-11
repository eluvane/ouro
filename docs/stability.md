<p align="center">
  <img
    width="100%"
    src="https://capsule-render.vercel.app/api?type=waving&amp;height=220&amp;color=0:0B1220,50:1E1B4B,100:4F46E5&amp;text=STABILITY&amp;fontColor=E2E8F0&amp;fontSize=46&amp;fontAlignY=50"
    alt="STABILITY banner"
  />
</p>

# Stability and compatibility

Ouro is pre-1.0 research software. The project is still refining the language,
runtime, package model, tooling, and bootstrap path, so compatibility is
narrower than it will be for a stable release.

## Versioning

The repository version is currently `0.1.0`. Release tags use `v<version>`.

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
rejected, evaluated, imported, packaged, or invoked differently.

Examples include:

- syntax removal or precedence changes;
- new or changed typechecking behavior;
- standard-library path or signature changes;
- CLI flag, output, or exit-status changes;
- package manifest or lockfile changes;
- diagnostic code changes used by tools;
- a new trusted component or core-artifact version.

## Experimental areas

The following areas are especially likely to change before 1.0:

- effect-handler syntax and semantics;
- package and registry conventions;
- LSP behavior and editor integration;
- runtime and IO breadth;
- module and import ergonomics;
- self-hosting and bootstrap artifacts;
- generated-development and synthesis interfaces.

## Assurance is separate from compatibility

Compatibility describes whether an interface stays the same. It does not make
that interface trusted.

Kernel checking establishes well-typed core declarations under the implemented
rules. It does not prove runtime safety, external process behavior, package
authenticity, scientific correctness, or the truth of an axiom. Those claims
require separate evidence.

<p align="center">
  <img
    width="100%"
    src="https://capsule-render.vercel.app/api?type=waving&amp;height=220&amp;color=0:0B1220,50:1E1B4B,100:4F46E5&amp;section=footer"
    alt=""
  />
</p>
