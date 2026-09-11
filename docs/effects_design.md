<p align="center">
  <img
    width="100%"
    src="https://capsule-render.vercel.app/api?type=waving&amp;height=220&amp;color=0:0B1220,50:1E1B4B,100:4F46E5&amp;text=EFFECTS&amp;fontColor=E2E8F0&amp;fontSize=54&amp;fontAlignY=50"
    alt="EFFECTS banner"
  />
</p>

# Effects and IO

Ouro represents effects as checked Core. The compiler checks the complete
declaration closure after supported handler lowering; console, filesystem, process, clock, and other
host behavior are implemented by the standard library and runtime adapters.

## IO programs

Runnable programs export `main : IO Unit`:

```ouro
import "../../std/io.ouro";

-- @entry main
def main : IO Unit :=
  do println "hello";
     exit 0
```

The current `do` subset supports sequencing and `let!`:

```ouro
def echo : IO Unit :=
  do let! line := readLine;
     println line
```

These forms lower through the existing IO representation. They do not add
effectful computation to the pure typechecker.

## Runtime surface

`std/runtime.ouro` declares checked String, standard-stream/exit, argument,
environment, clock, filesystem, temporary-file and process-capture intrinsics.
[TCB](tcb.md) describes their checking and execution boundaries. User-facing
wrappers live primarily in:

- `std/io.ouro` for console IO, arguments, environment variables, time, exit,
  and child processes;
- `std/fs.ouro` for files and directories;
- `std/async.ouro` for the current sequential sleep helper;
- `std/http.ouro` for HTTP message handling and the native Windows POST helper.

Programs built with `scripts/build_tool.sh` link the C runtime and IO host under
`runtime/`.

The experimental Windows native path preserves exact stdout/stderr bytes,
including NUL, and performs no newline conversion. Writes and exit remain
deferred actions when stored or passed as values. A write, staging-allocation,
or cleanup failure terminates with status 73. Native `flush` is a deferred
no-op because these writes are synchronous; native `exit` accepts a Nat
through 4294967295 and uses status 73 when conversion overflows. The
transitional C host retains its existing text-stream and exit behavior.

Native `readLine` and `readBytes` are reusable deferred actions. `readLine`
consumes through LF or at most 8,191 bytes, removing only LF and retaining
CR. Bytes beyond that limit remain for the next read. `readBytes n` waits
for `n` bytes or EOF; a short result means EOF. Neither action reads ahead,
and `readBytes 0` returns an empty string without inspecting stdin. Native
input preserves NUL and other byte values; the transitional C String bridge
retains its embedded-NUL limitation. Count overflow, invalid handles, OS
errors, allocation failure, and failed staging cleanup terminate with
status 73. The existing `IO String` signatures remain unchanged.

Native `now` reads UTC on each execution of the action and returns decimal
Unix-epoch milliseconds rounded down, including negative values before 1970.
It uses the Windows 8+ precise wall clock; allocation, query, and cleanup
failures terminate with status 73. Wall time is not a monotonic interval clock.

Native `argv` is a reusable deferred action. It retains `argv[0]`, order,
and empty arguments, converting Windows UTF-16 strictly to managed UTF-8
strings. Each argument scan permits at most 32,768 UTF-16 code-unit probes,
including the terminating NUL: at most 32,767 non-NUL code units. This is
a scan bound; the live Windows argv owner supplies the storage contract.

Native `env_get name` captures its name and reads the environment each
time the resulting action runs. A missing variable or empty name returns
`Nothing`; a present empty value returns `Just ""`. Lookup performs one
sizing query and one fill. Growth, shrinkage, disappearance between those
calls, a NUL in the name, malformed Unicode, or a host/conversion failure
terminates with status 73. A value changed to another of the same length
is the value observed by the fill; lookup provides no atomic snapshot.

Both adapters release owned raw buffers in reverse allocation order.
The argv table is closed before its owner cell is freed. Failed cleanup
still attempts every remaining owned release and terminates with status
73. Managed results and captured names remain GC roots across raw calls.

Native `fs_read` and `fs_write` preserve all file-content bytes, including NUL
and non-UTF-8 bytes, without newline conversion. Paths are nonempty strict
UTF-8 with no embedded NUL and are passed to Windows as UTF-16. Construction
and partial application only capture arguments; each execution reopens the
file. A write replaces the file contents, including truncating an existing
file to zero bytes for an empty String. The opened final component must not
be a reparse point; this is checked before truncation.

Reading captures the opened file's size once and reads exactly that many
bytes, retrying positive partial transfers. Later growth is ignored; early
EOF or another read failure terminates with status 73. This does not provide
an atomic content snapshot. Writes also retry positive partial transfers;
a failed write can leave a prefix in the file. Invalid paths, open, size,
prepare, transfer, raw-allocation and cleanup failures terminate with status
73. Cleanup attempts to close the owned handle before releasing raw pages in
reverse order and attempts every remaining release even after an error. Managed results
and captured paths/content remain roots across raw calls. Shared managed-heap
exhaustion is process-terminal and is not intercepted by these local scopes.

The transitional C file host preserves file-content bytes by length, and
String equality compares the full byte sequence, including bytes after NUL.
Its failure behavior remains different: failed opens and incomplete `fread`
calls return an empty String, write failures can return Unit, and close status
is ignored. Callers that publish artifacts must verify staged bytes before
replacing an existing output.

Native `fs_exists` and `fs_is_dir` query Win32 path attributes each time their
action executes. Empty paths, missing entries and ordinary query errors return
`False`. Existence uses query success; directory checks use the directory bit,
including on reparse points. A live or dangling directory junction therefore
reports `True` for both predicates. These are attribute queries and do not
provide the no-follow safety classification of `prim_fs_kind`.

Paths use strict UTF-8 with no embedded NUL. Invalid encoding, invalid raw
storage, allocation and cleanup failures terminate with status 73. Captured
paths and managed Bool results remain rooted across raw calls; all owned raw
pages are released. Following Win32, `file/` and `file\` return `False`, while
trailing separators on directories remain accepted. This differs from the
transitional C CRT's trailing-separator and NUL behavior. The native
`prim_fs_kind` classification is described in the [practical surface](practical_stdlib.md).

Native `fs_list` returns entry names, excluding only `.` and `..`. Names are
converted from bounded, terminated UTF-16 to UTF-8 without replacement. It
preserves the order reported by Windows; that order is unspecified. Callers
requiring a stable order must sort the returned names themselves. Construction
and aliases capture the path, and each action execution reads the directory
again. Earlier list results remain ordinary managed values across collection.

Both listing and `prim_fs_listable` first open the literal path with directory
list/read-attributes access and check the directory bit on that handle.
Listability returns False when this probe cannot establish an accessible
directory, including a missing path or a file. A successful probe returns True
for an empty directory. Listing appends a search wildcard, preserving a bare
drive's current-directory meaning (`I:*`). Only the first search's no-match
result may produce an empty list after the successful probe.
Subsequent iteration failures never return an empty or partial list.

Empty paths, embedded NUL and malformed UTF-8 arguments fail with status 73.
Listing also fails with 73 on probe/search errors or malformed returned names.
Raw-allocation and cleanup failures are fatal for both actions. A successful
probe handle is closed with CloseHandle before enumeration starts; every
successful search handle is closed with FindClose, including after conversion
or iteration failure. Cleanup then attempts all owned raw releases. Global
managed-heap exhaustion remains outside these local cleanup scopes.

The probe and enumeration are separate operations: a directory can change
between them or during iteration. This provides neither an atomic snapshot
nor a no-follow guarantee. The transitional C list host retains its prior
behavior: it prepends names, returns an empty list after an open failure,
ignores close status, and does not distinguish iteration errors from EOF.
Its listability probe still returns a Boolean from opendir success. These
hosts do not promise the same enumeration order or error handling.

Native `fs_mkdir_p` attempts parent creation before the final directory;
`fs_remove` removes a file entry or an empty directory without enumerating
children. Empty paths do nothing. Their low-level Unit result does not
confirm success: ordinary OS errors return Unit, while invalid-parameter
status 87, malformed UTF-8/NUL, raw allocation and cleanup failures terminate
with status 73. Use `fs_mkdir_p_checked` and `fsx_remove_if_exists` to check the
postcondition. Parent creation may leave earlier directories after a later
failure; these operations provide neither rollback nor atomicity.

Native `fs_copy` invokes `CopyFileW` with overwrite enabled. It preserves
binary contents, including an empty source replacing a nonempty target.
Both paths must be nonempty strict UTF-8 with no NUL. Copy errors, invalid
parameters, conversion, raw allocation and cleanup failures terminate with
status 73. Copy follows Windows path behavior and does not apply the
`fs_write` final-component reparse guard. The low-level operation does not
create missing target parents; `fs_copy_checked` composes parent creation
and postcondition checks. It provides no atomic snapshot or rollback.

For all three operations, construction and partial application capture
arguments; a stored action performs new filesystem work on each execution.
Captured paths and results remain roots across raw calls. Cleanup attempts
every owned raw release in reverse order, including after an error. Windows
owns handles used internally by `CopyFileW`. Shared managed-heap exhaustion
is process-terminal and remains outside these local cleanup scopes. The
transitional C mutation/copy host retains its silent failures, narrow paths
and ignored close status; its copy implementation does not provide the
native failure contract.

`prim_fs_rename source target` is a deferred same-volume replacement action
returning an OS status as `Nat`: zero is success. The Windows implementation
uses `MoveFileExW` with replacement enabled and without cross-volume copying
or delayed actions. A failed rename preserves the source and destination;
callers own any staging cleanup. `fs_rename_checked` adds path/file checks and
returns a typed error with the failed destination and OS status. It does not
create target parents.

Native rename uses strict UTF-8 paths and the existing fatal path-conversion
and cleanup contract. Its C-host adapter rejects empty paths and embedded NUL
with an explicit parameter error, converts Windows UTF-8 paths strictly to
UTF-16, and returns `GetLastError` after an OS refusal. On POSIX it uses
`rename` and `errno`, retaining the platform's byte-path semantics. Neither
adapter falls back to copy/delete or promises power-loss durability.

Native `prim_fs_realpath` captures its path and resolves it anew whenever the
action runs. It follows links and junctions, returns UTF-8 with forward
slashes, removes the Windows extended path prefix, and keeps UNC paths
starting with `//`. Empty paths and OS unavailability return an empty String.
Paths must be strict UTF-8 without NUL; malformed text, invalid raw storage,
raw allocation, incomplete conversion/fill and cleanup failures exit 73.

Resolution opens the target, performs one bounded sizing query and one fill,
and converts the complete result. Growth beyond that capacity fails without
returning partial text. The action attempts to close its handle and release
every owned conversion buffer, preserving the result as a managed root
during cleanup. Shared managed-heap exhaustion remains outside these local
cleanup scopes. Resolution provides no atomic filesystem snapshot; the
transitional C host retains its previous error and cleanup behavior.
Temporary-file and process-capture lowering also have native runtime owners;
the compiler producer and compatibility launchers remain host-bound.

`prim_process_capture` returns an exit code and separate stdout/stderr strings
as `Pair Nat (Pair String String)`. `prim_proc_exec` wraps that checked action
into the existing `ProcResult`, preserving `proc_exec` consumers. Reusing a
stored action launches another child. Child execution does not inherit the
caller's stdin; this API has no timeout or cancellation argument. The
transitional C Windows adapter retains its private-directory command launcher.
The typed scientific examples build their execution-evidence layer on this API.

`prim_process_inherit` is a separate deferred action with the checked result
`Pair Nat Nat`: OS error and child exit. The native owner inherits all three
standard handles, directory and environment, and preserves the complete U32
exit code after a successful wait. It retains a non-inheritable child job
handle with `JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE`; `PROC_THREAD_ATTRIBUTE_JOB_LIST`
attaches that job within `CreateProcessW`, before child execution. No new
console, process group, breakaway permission or Ctrl+C-ignore state is set.
The adapter closes the owned job and raw argument storage before returning.
The temporary C host returns `(120, 0)` when this action executes. Construction
and partial application do not create a child.

## Experimental handlers

The repository includes a narrow one-shot handler subset using `effect`,
`perform`, and `handle`. It exists to exercise parsing, lowering, and checked
examples; it is not a complete algebraic-effects system.

Examples live in:

- `samples/tutorial/06_effects.ouro`;
- `samples/examples/effect_demo.ouro`;
- `samples/examples/effect_ask_handler.ouro`;
- `samples/examples/effect_nested_ask.ouro`;
- `samples/examples/effect_ask_io.ouro`.

Check a sample with:

```sh
sh scripts/ouro1.sh check samples/tutorial/06_effects.ouro
```

The current implementation does not promise effect rows, multi-shot
continuations, general handler composition, or a stable public handler syntax.

## Networking

`std/http.ouro` provides HTTP message codecs and `http_post`, backed by the
checked `prim_http_request` intrinsic (`ouro.http.post`). Native Windows
lowering calls WinHTTP directly; TLS certificate verification belongs to the
OS. Requests do not require `curl`, shell commands, or temporary body files.

The intrinsic returns the HTTP status, exact response bytes, and a transport
failure reason. Transport failures use status `0`; HTTP errors retain their
server status and body. `http_post` preserves these fields in `HttpResp` but
currently returns an empty response-header list. The transitional C host has
no HTTP transport: executing its deferred action returns status `0`, an empty
body, and `HTTP transport unavailable in C host` as the reason.

This remains an experimental Windows runtime surface. Source wiring alone
does not establish native execution, portability, or isolated-host bootstrap.

## Trust boundary

Runtime primitives, host processes, files, clocks, and network transports are
outside the pure checker. Compiler checking establishes that the elaborated
Core is well-typed under the implemented rules and assumptions; it does not
prove that a host operation is available, deterministic, memory-safe, or
faithful to an external specification.

<p align="center">
  <img
    width="100%"
    src="https://capsule-render.vercel.app/api?type=waving&amp;height=220&amp;color=0:0B1220,50:1E1B4B,100:4F46E5&amp;section=footer"
    alt=""
  />
</p>
