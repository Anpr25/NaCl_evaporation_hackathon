# decisions/ — cross-developer log

One file per person. Write here when you have done something the other three need to know
about, or made a call they might otherwise undo by accident.

*Proposed convention, set by D's first entry. Change it if something else suits you better —
just change it for everyone.*

## What goes where

| | |
|:--|:--|
| `decisions/X.md` | **What I did and what it means for you.** Newest entry at the top, dated. |
| [`../STATUS.md`](../STATUS.md) | **Project truth.** One shared view: what works, the decision log, the backlog. |
| [`../PLAN.md`](../PLAN.md) | **The architecture and who owns what.** Changes rarely. |
| [`../GLOSSARY.md`](../GLOSSARY.md) | **Jargon in plain English.** IR, FSM, omc, L0/L1/L2. |

Rule of thumb: your file is *your* running log, STATUS.md is the *shared* state. When
something in your log becomes a project fact, also put it in STATUS.md — §2 if it now works,
§3 if it was a decision, §4 if it created work, §6 if it was a bug worth remembering.

## Entry shape

```markdown
## YYYY-MM-DD — one-line summary

**Status:** what changed, in a sentence.

### ⚠ Affects you
Anything another person must know. Name them: "C — I changed the picker schema."
If nothing affects anyone, say so and keep the section out.

### What I did
Evidence, not adjectives. Numbers, before/after, file paths.

### Still open
What you did not finish, and what unblocks it.
```

## Two habits worth keeping

**Put the number in.** "Faster" is not useful; "13.3 → 43.1 tok/s" is. Someone reading this
at 2am needs to know whether to care.

**Write down what you got wrong, not just what you built.** Half of D's first entry is bugs
found in D's own code. That is the useful half — it is what stops the next person losing the
same hour, and it is most of what the honesty score rewards.
