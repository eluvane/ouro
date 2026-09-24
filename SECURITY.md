# Security policy

## Supported versions

Until tagged release support is announced, security fixes target the current
`main` branch. See [Stability](docs/stability.md) for pre-1.0 compatibility.

A future security advisory will identify affected tags and state whether a
backport is available. No compatibility or patch-support window should be
inferred from the repository version alone.

## Reporting a vulnerability

Do not open a public issue for a suspected vulnerability.

Use GitHub Private Vulnerability Reporting from the repository's **Security**
tab, or the **Security vulnerability** contact link in the issue chooser. This
creates a private advisory visible to the maintainers.

Include, when available:

- the affected commit or tag;
- the operating system and toolchain;
- a minimal input and the exact command;
- the observed impact;
- whether the issue involves the kernel, runtime, generated artifacts,
  packages, workflows, or release files;
- logs or reports that do not contain unrelated secrets.

Maintainers will confirm receipt and coordinate investigation and disclosure
through the private advisory. Ouro does not currently promise a fixed response
SLA, but reporters will be told when the issue can be disclosed safely.

## Scope

Security reports may cover the compiler and kernel, C runtime and IO host,
package verification, generated-artifact promotion, GitHub workflows, release
packaging, or other repository-owned tooling.

Ordinary language bugs, confusing diagnostics, performance regressions, and
documentation errors can use the public issue forms unless they create a
security impact.
