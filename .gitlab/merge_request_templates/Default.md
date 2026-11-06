## What
<!-- One-line summary, then the changes grouped by requirement or feature.
     Describe user-visible behaviour, not implementation.
     State which tests were added or changed. -->

## Why
<!-- The problem or need, who is affected, what was wrong before.
     A reason, not a restatement of What. -->

## How
<!-- One bullet per changed area: `path` - what was done.
     Group generated files and lockfiles into a single line. -->

## Verification
<!-- The commands actually run, each with its real result, using this
     repo's own commands. Never invent or round results. If something
     was not run, write "not run" and why. Manual testing only if it
     was really performed; otherwise "Manual: not performed" plus what
     a reviewer should check by hand. -->

## Risk & Rollback
Security impact:
<!-- Fill in the Security impact line above: "none" or the threat note,
     new dependencies, new secrets or config keys, changed permissions,
     new external inputs. Then: two-way door (easy to revert, additive,
     backward compatible) or one-way door (migration, schema/data
     change, breaking API or protocol, deletion), one sentence why.
     Blast radius: what is affected, what is explicitly untouched.
     Exact rollback steps. -->

## Context
<!-- Resolves: issue/ticket or "None". Relates to: or "None".
     ADR/RFC: or "None". If stacked on other branches, say which and
     the merge order. -->

<!--
Human author checklist (delete this comment before submitting):
- [ ] Tests added or changed for the behaviour change
- [ ] Docs updated where behaviour or contracts changed
- [ ] No secrets committed
- [ ] Rollback steps understood and accurate
-->
