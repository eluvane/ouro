<p align="center">
  <img
    width="100%"
    src="https://capsule-render.vercel.app/api?type=waving&amp;height=220&amp;color=0:0B1220,50:1E1B4B,100:4F46E5&amp;text=SCIENTIFIC&amp;fontColor=E2E8F0&amp;fontSize=46&amp;fontAlignY=50"
    alt="SCIENTIFIC banner"
  />
</p>

# Typed external-tool execution

This directory contains a small reusable example for connecting typed inputs to
an external process and constructing a typed output only after the process
boundary succeeds.

It is ordinary Ouro library code outside the standard library and logical
kernel.

## Flow

```text
typed input
  -> typed tool specification
  -> typed invocation
  -> external process
  -> captured execution record
  -> successful stage evidence
  -> typed output with provenance
```

The main modules are:

- `identity.ouro` — source, content, transformation, and derived-artifact
  identities;
- `execution_evidence.ouro` — process attempts and successful typed evidence;
- `transformation.ouro` — shared transformation metadata;
- `external_tool.ouro` — the process runner facade.

The input and output parameters are type indices. Evidence produced for one
stage cannot be passed to a completion function for another stage without a
type error.

## Process boundary

The runner records the declared tool and version, ordered arguments and
parameters, environment and determinism declarations, input identities, output
contract, exit status, and stdout/stderr metadata.

Before launch it clears the expected output path. A successful typed result
requires both exit status zero and a newly present regular output file. Failed
or missing-output attempts retain diagnostic metadata but do not receive
successful output evidence.

## Identity and reproducibility

Artifact identity, optional content identity, and transformation identity are
separate concepts. The current runner does not hash scientific output files, so
a transformation hash is never presented as a file-content digest.

Complete transformation metadata supports stable identification of an
invocation. It does not prove bit-for-bit determinism, enforce the declared
environment, or verify that the executable version is truthful.

## Scope

This example does not inspect scientific file formats or prove scientific
correctness. Constructors remain ordinary public values in the current module
system, so the example is a checked API pattern rather than a capability
security boundary.

It is not a scheduler, workflow DSL, container runtime, cache, provenance
database, or distributed executor.

Check the reusable layer with:

```sh
sh scripts/ouro1.sh check samples/scientific/external_tool.ouro
sh scripts/samples_suite.sh
```

The domain-specific examples are in
[`samples/bioinformatics/`](../bioinformatics/README.md).

<p align="center">
  <img
    width="100%"
    src="https://capsule-render.vercel.app/api?type=waving&amp;height=220&amp;color=0:0B1220,50:1E1B4B,100:4F46E5&amp;section=footer"
    alt=""
  />
</p>
