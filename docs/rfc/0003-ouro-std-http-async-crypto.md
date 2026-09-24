# RFC 0003: Word, crypto, HTTP-message, and sequential sleep library slice

- Status: accepted
- Authors: Ouro maintainers
- Created: 2026-08-21

## Summary

Add a bounded standard-library slice for word operations, SHA-256/HMAC,
HTTP/1.0 message handling, and sequential sleep without adding a C HTTP stack,
TLS implementation, digest primitive, scheduler, or kernel rule.

## Motivation

Pure Peano arithmetic is not a practical implementation base for SHA-256, while
moving complete crypto and networking libraries into the host would make the
language examples thinner and the runtime surface much larger.

The selected boundary adds host-fast 32-bit word operations and leaves the
higher-level algorithms and codecs in Ouro.

## Decision

| Module | Implemented role | Explicit limit |
| --- | --- | --- |
| `std/word.ouro` | 32-bit bitwise, shift, rotate, and addition operations | Not a new kernel numeric type |
| `std/crypto.ouro` | SHA-256 and HMAC-SHA256 over the current string/byte model | No signatures or TLS |
| `std/http.ouro` | HTTP/1.0 request/response codec and host-command-backed POST | No native socket or TLS stack |
| `std/async.ouro` | Sequential sleep and delay helper | No scheduler, race, or green threads |

At this decision's acceptance, `prim_http_post` was unwired and the request
helper delegated to host `curl` through the process API. Word operations used
runtime acceleration with ordinary Ouro definitions for checking. For current
transport behavior, see [Effects and IO](../effects_design.md).

## Compatibility

The change is additive in the pre-1.0 standard library. Programs that do not
import the modules are unaffected.

## Trust

No kernel rule changes. Runtime word operations, host `curl`, clocks, and
processes remain outside the logical trusted computing base.

## Validation and documentation

The crypto runtime fixture, example program, generated API pages,
[Effects and IO](../effects_design.md), and changelog cover the implemented
slice.
