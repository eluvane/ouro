"""Declaration and prose association oracle, authored independently of scanning."""
from __future__ import annotations


def program(seed, import_path):
    name = f"documented{seed}"
    header = f"Module documentation {seed}. A second header line."
    signature = f"def {name} (n : Nat) : Nat"
    prose = f"Generated documentation for {name}. This sentence belongs to the same paragraph."
    source = f'''-- Module documentation {seed}.
-- A second header line.

-- @entry {name}

import "{import_path}";

-- Generated documentation for {name}.
-- This sentence belongs to the same paragraph.
{signature} := S n;

def silent{seed} : Nat := Z;

-- Detached paragraph {seed} must not attach to a declaration.

def orphan{seed} : Nat := {seed % 7};

-- Polymorphic signature {seed}.
def apply{seed} (A : Type) (f : A -> A) (x : A) : A := f x;

-- Continuation signature {seed}.
def pair{seed} (a : Nat)
    (b : Nat) : Pair Nat Nat :=
    MkPair Nat Nat a b;

-- Type documentation {seed}.
inductive Tone{seed} : Type :=
  | Light{seed} : Tone{seed}
  | Dark{seed} : Tone{seed};

-- Body documentation {seed}.
def shade{seed} (s : Tone{seed}) : Nat :=
    match s with
    -- Inner comment {seed} must not attach to the next declaration.
    | Light{seed} => Z
    | Dark{seed} => S Z
    end;

def last{seed} : Nat := {seed % 7};

-- Native string type {seed}.
-- The keyword extern in prose is not a declaration.
intrinsic String : Type := "ouro.string";

-- Detached native paragraph {seed} must not attach.

intrinsic Word{seed} : Type := "ouro.u32";
intrinsic Action{seed} : Type -> Type := "ouro.runtime";

-- Foreign signature {seed}.
-- @entry pid{seed}
extern pid{seed} : Action{seed} Word{seed} := "windows-x86_64" "win64" "kernel32.dll" "GetCurrentProcessId" "maygc";

-- A role annotation does not declare another global.
representation Tone{seed} := "ouro.bool";

-- Native words inside a body remain source text.
def native_text{seed} : String := "intrinsic Decoy : Type; extern Decoy : Type;";
'''
    sections = [
        ("def", name, signature, prose),
        ("def", f"silent{seed}", f"def silent{seed} : Nat", ""),
        ("def", f"orphan{seed}", f"def orphan{seed} : Nat", ""),
        ("def", f"apply{seed}", f"def apply{seed} (A : Type) (f : A -> A) (x : A) : A", f"Polymorphic signature {seed}."),
        ("def", f"pair{seed}", f"def pair{seed} (a : Nat)", f"Continuation signature {seed}."),
        ("inductive", f"Tone{seed}", f"inductive Tone{seed} : Type", f"Type documentation {seed}."),
        ("def", f"shade{seed}", f"def shade{seed} (s : Tone{seed}) : Nat", f"Body documentation {seed}."),
        ("def", f"last{seed}", f"def last{seed} : Nat", ""),
        ("intrinsic", "String", "intrinsic String : Type",
         f"Native string type {seed}. The keyword extern in prose is not a declaration."),
        ("intrinsic", f"Word{seed}", f"intrinsic Word{seed} : Type", ""),
        ("intrinsic", f"Action{seed}", f"intrinsic Action{seed} : Type -> Type", ""),
        ("extern", f"pid{seed}", f"extern pid{seed} : Action{seed} Word{seed}", f"Foreign signature {seed}."),
        ("def", f"native_text{seed}", f"def native_text{seed} : String", "Native words inside a body remain source text."),
    ]
    paragraphs = [header, f"Declarations: {len(sections)}."]
    for kind, identifier, declaration, comment in sections:
        paragraphs.extend([f"## {kind} {identifier}", f"```\n{declaration}\n```"])
        if comment:
            paragraphs.append(comment)
    return source, "\n\n".join(paragraphs) + "\n", signature, prose
