---
name: react
description: React and TypeScript component discipline — small typed components, state kept as local as possible, hooks used lawfully, effects only for true side effects, stable keys, accessible markup, and server state kept out of component state. Applies when planning, implementing, reviewing or fixing React front-ends.
---

# React craft

## Components and props

- Components do one thing and stay small enough to read whole.
  Split by responsibility (data, layout, interaction), not by
  line count alone.
- Type every props object; never `any` to silence the compiler.
  Props are read-only inputs — a component never mutates them or
  reaches into a parent's state.
- Derive values during render instead of storing copies in state:
  if it can be computed from props/state, it is not state.
- Lists render with stable, data-derived `key`s — never the array
  index for anything that can reorder, be filtered or be deleted.

## State and effects

- Keep state as local as possible; lift it only to the nearest
  common ancestor that actually needs it. Reach for context or a
  store only when prop passing becomes genuinely unwieldy, and
  say why.
- Server data is not component state: fetch it through the
  project's data layer (query hooks/services) with explicit
  loading, error and empty states rendered for every view — a
  spinner forever and a silent blank are both defects.
- `useEffect` is only for synchronising with the outside world
  (subscriptions, timers, the DOM, network not handled by the
  data layer). Never use an effect to transform data for render
  or to respond to a user event — use the event handler.
  Every effect's dependencies are complete and honest; cleanup
  functions undo whatever the effect set up.

## Hooks, forms and accessibility

- Hooks are called unconditionally at the top level of components
  and custom hooks — never in loops, conditions or callbacks.
  Custom hooks encapsulate reusable stateful logic and are named
  `useX`.
- Forms are controlled (or deliberately uncontrolled with refs);
  validate at the boundary, show field-level errors, and disable
  submission while a request is in flight to prevent duplicates.
- Markup is semantic and accessible by default: real buttons and
  links (not clickable divs), labels tied to inputs, sufficient
  contrast, keyboard-reachable interactions, and `alt` text that
  describes images. Interactive elements work without a mouse.
- Never inject unsanitised HTML (`dangerouslySetInnerHTML`) with
  user-derived content (see the security skill).
