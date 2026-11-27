# std/types.ouro

Shared data declarations and checked representation identities. This module has no executable helpers or runtime/platform imports.

Declarations: 8.

## inductive Nat

```ouro
inductive Nat : Type
```

## inductive Bool

```ouro
inductive Bool : Type
```

## inductive List

```ouro
inductive List (A : Type) : Type
```

## inductive Pair

```ouro
inductive Pair (A : Type) (B : Type) : Type
```

## inductive Maybe

```ouro
inductive Maybe (A : Type) : Type
```

## inductive Either

```ouro
inductive Either (A : Type) (B : Type) : Type
```

## inductive Ordering

```ouro
inductive Ordering : Type
```

## inductive Unit

```ouro
inductive Unit : Type
```
