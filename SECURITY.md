# Security policy

## Supported versions

Security fixes target `main` until the project announces support for tagged
releases. Consult individual advisories for affected tags and backport
availability. See the [pre-1.0 compatibility policy](docs/stability.md).

## Reporting a vulnerability

Do not open a public issue for a suspected vulnerability.

Use [GitHub Private Vulnerability Reporting](https://github.com/eluvane/ouro/security/advisories/new).
The **Security vulnerability** contact in the issue chooser opens the same
form. GitHub shares the report with the repository maintainers.

Include the available details.

- Affected commit or tag
- Operating system and toolchain version
- Minimal input and exact command
- Observed impact and the affected component
- Relevant logs with unrelated secrets removed

Maintainers confirm receipt, coordinate the investigation in the private
advisory, and tell reporters when disclosure can proceed. Response times vary.

## Scope

Security reports may cover the compiler and kernel, C runtime and IO host,
package verification, generated-artifact promotion, GitHub workflows, release
packaging, or other repository-owned tooling.

Ordinary language bugs, confusing diagnostics, performance regressions, and
documentation errors can use the public issue forms unless they create a
security impact.
