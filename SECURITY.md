<p align="center">
  <img
    width="100%"
    src="https://capsule-render.vercel.app/api?type=waving&amp;height=220&amp;color=0:0B1220,50:1E1B4B,100:4F46E5&amp;text=SECURITY&amp;fontColor=E2E8F0&amp;fontSize=54&amp;fontAlignY=50"
    alt="SECURITY banner"
  />
</p>

# Security policy

## Supported versions

Ouro is pre-1.0 research software. Until tagged release support is announced,
security fixes target the current `main` branch.

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

<p align="center">
  <img
    width="100%"
    src="https://capsule-render.vercel.app/api?type=waving&amp;height=220&amp;color=0:0B1220,50:1E1B4B,100:4F46E5&amp;section=footer"
    alt=""
  />
</p>
