# std/tactics.ouro

Tactics are data only; this module does not add proof automation to the kernel.

Declarations: 21.

## inductive Lst

```
inductive Lst (A : Type) : Type
```

## inductive Bool

```
inductive Bool : Type
```

## def andb

```
def andb (x : Bool) (y : Bool) : Bool
```

## def orb

```
def orb (x : Bool) (y : Bool) : Bool
```

## inductive Ty

```
inductive Ty : Type
```

## def eqTy

```
def eqTy : Ty -> Ty -> Bool
```

## inductive Goal

```
inductive Goal : Type
```

## inductive Result

```
inductive Result (A : Type) : Type
```

## inductive Tactic

```
inductive Tactic : Type
```

## def inCtx

```
def inCtx (t : Ty) : Lst Ty -> Bool
```

## def introStep

```
def introStep (g : Goal) : Result Goal
```

Target a->b: extend context with a, target b.

## def assumptionStep

```
def assumptionStep (g : Goal) : Result Goal
```

## def exactStep

```
def exactStep (t : Ty) (g : Goal) : Result Goal
```

## def applyStep

```
def applyStep (f : Ty) (g : Goal) : Result Goal
```

If f : a->b and b matches target, remaining subgoal is a.

## def bind

```
def bind (r : Result Goal) (k : Goal -> Result Goal) : Result Goal
```

## def runStep

```
def runStep : Tactic -> Goal -> Result Goal
```

Interpret one tactic; Then sequences.

## def seq

```
def seq (t1 : Tactic) (t2 : Tactic) (g : Goal) : Result Goal
```

## def isSolved

```
def isSolved (g : Goal) : Bool
```

## def demoGoal

```
def demoGoal : Goal
```

Demo: Base -> Base by intro; assumption.

## def demoScript

```
def demoScript : Tactic
```

## def demoResult

```
def demoResult : Result Goal
```
