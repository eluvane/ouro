<p align="center">
  <img
    width="100%"
    src="https://capsule-render.vercel.app/api?type=waving&amp;height=220&amp;color=0:0B1220,50:1E1B4B,100:4F46E5&amp;text=RFC%200001&amp;fontColor=E2E8F0&amp;fontSize=54&amp;fontAlignY=50"
    alt="RFC 0001 banner"
  />
</p>

# RFC 0001: Strict project syntax and quality policy

- Status: accepted
- Authors: Ouro maintainers
- Created: 2026-08-17

## Summary

Project-owned Ouro code uses a stricter profile than the full parser surface.
The profile favors forms with clear types, predictable tooling, and practical
migration paths. Repository quality rules are versioned through stable
diagnostics, fixtures, and explicit debt rather than informal review taste.

## Motivation

Keeping old and new spellings indefinitely increases formatter, analyzer,
documentation, and maintenance cost. Immediate parser removal is also risky
when the bootstrap compiler and project source must migrate together.

A repository profile provides a middle path: precise rules can block new debt
without claiming that every discouraged form has already disappeared from the
language grammar.

## Decision

`quality/diagnostics.json` records the diagnostic, replacement, profile levels,
and fixture coverage. `scripts/strict_quality_firewall.py` enforces the
registry, suppression rules, and debt manifest.

The strict project style prefers:

- records and projections over repeated manual accessors;
- typed list literals over literal-shaped constructor chains;
- `do let!` over retired bind notation;
- pipes where final-argument data flow is clearer;
- local opens and explicit aliases over namespace leakage;
- structured diagnostics over ad-hoc panic text;
- documented public APIs and bounded modules.

A rule may block source only when its replacement is implemented, documented,
and covered by fixtures. Broader or uncertain rules remain warnings.

## Compatibility

External experiments can use the `baseline` profile. Project, compiler, and
release profiles are stricter.

Existing repository debt is recorded in `quality/strict_debt_manifest.json`.
The gate rejects debt growth and requires the manifest to be updated when debt
shrinks. A future parser-level removal requires a separate compatibility
decision.

## Trust

The quality firewall is outside the logical trusted computing base. It may
reject repository source as policy, but it cannot accept a core declaration or
change kernel semantics.

## Validation and documentation

The decision is covered by the quality fixture manifest, strict firewall,
analyzer and lint suites, [Quality tools](../quality.md),
[Surface syntax](../syntax.md), and the changelog.

<p align="center">
  <img
    width="100%"
    src="https://capsule-render.vercel.app/api?type=waving&amp;height=220&amp;color=0:0B1220,50:1E1B4B,100:4F46E5&amp;section=footer"
    alt=""
  />
</p>
