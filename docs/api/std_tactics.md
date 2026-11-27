# std/tactics.ouro

Tactics are data only; this module does not add proof automation to the kernel.

Declarations: 21.

## inductive Lst

```ouro
inductive Lst (A : Type) : Type
```

## inductive Bool

```ouro
inductive Bool : Type
```

## def andb

```ouro
def andb (x : Bool) (y : Bool) : Bool
```

## def orb

```ouro
def orb (x : Bool) (y : Bool) : Bool
```

## inductive Ty

```ouro
inductive Ty : Type
```

## def eqTy

```ouro
def eqTy : Ty -> Ty -> Bool
```

## inductive Goal

```ouro
inductive Goal : Type
```

## inductive Result

```ouro
inductive Result (A : Type) : Type
```

## inductive Tactic

```ouro
inductive Tactic : Type
```

## def inCtx

```ouro
def inCtx (t : Ty) : Lst Ty -> Bool
```

## def introStep

```ouro
def introStep (g : Goal) : Result Goal
```

Target a->b: extend context with a, target b.

## def assumptionStep

```ouro
def assumptionStep (g : Goal) : Result Goal
```

## def exactStep

```ouro
def exactStep (t : Ty) (g : Goal) : Result Goal
```

## def applyStep

```ouro
def applyStep (f : Ty) (g : Goal) : Result Goal
```

If f : a->b and b matches target, remaining subgoal is a.

## def bind

```ouro
def bind (r : Result Goal) (k : Goal -> Result Goal) : Result Goal
```

## def runStep

```ouro
def runStep : Tactic -> Goal -> Result Goal
```

Interpret one tactic; Then sequences.

## def seq

```ouro
def seq (t1 : Tactic) (t2 : Tactic) (g : Goal) : Result Goal
```

## def isSolved

```ouro
def isSolved (g : Goal) : Bool
```

## def demoGoal

```ouro
def demoGoal : Goal
```

Demo: Base -> Base by intro; assumption.

## def demoScript

```ouro
def demoScript : Tactic
```

## def demoResult

```ouro
def demoResult : Result Goal
```
