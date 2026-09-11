<p align="center">
  <img
    width="100%"
    src="https://capsule-render.vercel.app/api?type=waving&amp;height=220&amp;color=0:0B1220,50:1E1B4B,100:4F46E5&amp;text=DOCS&amp;fontColor=E2E8F0&amp;fontSize=54&amp;fontAlignY=50"
    alt="DOCS banner"
  />
</p>

# Ouro documentation

This index separates the material for language users from the material for
contributors and maintainers. Start with the shortest path that matches what
you are trying to do.

## Getting started

- [Public site](https://eluvane.github.io/ouro/) — hosted landing page and
  documentation shell. Source is `site/`.
- [Getting started](getting_started.md) — build the toolchain, check a module,
  evaluate an expression, and run a native program.
- [Tutorial samples](../samples/tutorial/README.md) — six small, checkable
  lessons.
- [Example gallery](../samples/examples/README.md) — IO, data, crypto, tests,
  and effect examples.
- [Practical programs](practical_programs.md) — runnable CLI/file/data tools
  using the current standard-library surface.
- [Practical standard library](practical_stdlib.md) — reusable CLI, text,
  collection, config, filesystem, table, and Result-style APIs for small tools.
- [Practical application surface](practical_application_surface.md) — an
  end-to-end JSON/CSV/config/filesystem/process tool built from reusable stdlib
  helpers.

## Language

- [Syntax](syntax.md) — the current surface language and its limits.
- [Design goals](design.md) — language direction, native toolchain contract,
  and non-goals.
- [Concept and native transition](ouro.md) — current direction and the retained
  historical research proposal for checked generation and self-application.
- [Effects and IO](effects_design.md) — the implemented IO boundary and the
  experimental handler subset.
- [Stability](stability.md) — what pre-1.0 compatibility means.
- [Standard-library API](api/README.md) — generated module reference.

## Tooling and packages

- [Tooling](tooling.md) — check, eval, format, analyze, lint, test,
  documentation, LSP, and editor integration.
- [Packages](pkg.md) — `Ouro.seal`, `Ouro.lock`, `coil`, local registries,
  vendoring, and verification.
- [Quality tools](quality.md) — analyzer families, diagnostics, strict
  profiles, and migration policy.
- [Native repository gates](native_repo_gates.md) — Ouro-owned policy,
  script inventory, parity evidence, and retirement checks.

## Compiler and trust

- [Architecture](architecture.md) — repository layers and the main compilation
  paths.
- [Canonical source pipeline](canonical_source.md) — internal compact compiler
  input, directive metadata, source mapping, and semantic/tooling hashes.
- [Build and bootstrap](build.md) — build configuration, caches, generated
  artifacts, and the stage loop.
- [Compiler checking](kernel_design.md) — Core, declaration checking, and typed failures.
- [Trusted computing base](tcb.md) — checker ownership and current host assumptions.
- [Core artifacts](kernel_core_artifact.md) — checked snapshots and the archived
  JSON replay format.

## Contributing and maintenance

- [Contributing](../CONTRIBUTING.md) — first build, focused tests, RFCs,
  generated artifacts, and pull requests.
- [Continuous integration](ci.md) — local profiles and hosted workflow roles.
- [OuroSmith](ouro_smith.md) — generated tests, independent oracles, replay,
  and migration of the manual corpus.
- [Releasing](releasing.md) — source package and release-candidate procedure.
- [RFCs](rfc/README.md) — design proposals and accepted decisions.
- [Roadmap](roadmap.md) — native transition stages and acceptance criteria.
- [Security policy](../SECURITY.md) — private vulnerability reporting.

<p align="center">
  <img
    width="100%"
    src="https://capsule-render.vercel.app/api?type=waving&amp;height=220&amp;color=0:0B1220,50:1E1B4B,100:4F46E5&amp;section=footer"
    alt=""
  />
</p>
