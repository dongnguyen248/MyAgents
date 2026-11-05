"""Shrinking SPEC/PLAN context to what one task item needs.

SPEC and PLAN were re-sent in full to every step of every task
item. These slicers keep the stable, relevant part:

- PLAN: the preamble (title, linked SPEC, milestones header) plus
  the ONE milestone block the task item belongs to
  (``milestoneRef``), plus a one-line index of the other
  milestones. Unparseable plans and unknown milestone refs fall
  back to the full text — a slicer must never lose information
  silently.
- SPEC: returned whole when below the threshold; otherwise the
  preamble plus the sections whose headings/bodies match the task
  item's vocabulary (title + description), always including the
  first section, within the same character budget.

Artifact ids and versions are untouched — only the prompt text
shrinks, so traceability is unaffected.
"""

from __future__ import annotations

import re

__all__ = ["SPEC_SLICE_THRESHOLD_CHARS", "slice_plan", "slice_spec"]

SPEC_SLICE_THRESHOLD_CHARS = 8000

_MILESTONE_HEADING = re.compile(r"^###\s+(M\d+):\s*(.+)$", re.MULTILINE)
_SECTION_HEADING = re.compile(r"^##\s+(.+)$", re.MULTILINE)
_WORD = re.compile(r"[a-z0-9]{4,}")
_STOPWORDS = {
    "this", "that", "with", "from", "must", "should", "when", "then",
    "than", "into", "have", "will", "each", "such", "other", "about",
    "which", "their", "there", "these", "those", "using", "used",
}


def slice_plan(plan_text: str, milestone_ref: str | None) -> str:
    """PLAN preamble + the referenced milestone's block only."""
    if not milestone_ref:
        return plan_text
    matches = list(_MILESTONE_HEADING.finditer(plan_text))
    if not matches:
        return plan_text
    target = next(
        (match for match in matches if match.group(1) == milestone_ref), None,
    )
    if target is None:
        return plan_text
    preamble = plan_text[: matches[0].start()].rstrip()
    start = target.start()
    end = len(plan_text)
    for match in matches:
        if match.start() > start:
            end = match.start()
            break
    else:
        # The target is the last milestone: a following '## '
        # section (if any) is not part of its block.
        following = _SECTION_HEADING.search(plan_text, target.end())
        if following:
            end = following.start()
    block = plan_text[start:end].rstrip()
    others = [
        f"{match.group(1)} — {match.group(2).strip()}"
        for match in matches if match.group(1) != milestone_ref
    ]
    parts = [preamble, block]
    if others:
        parts.append("Other milestones (not part of this task): " + "; ".join(others))
    return "\n\n".join(part for part in parts if part)


def _keywords(*texts: str) -> set[str]:
    words: set[str] = set()
    for text in texts:
        for word in _WORD.findall(text.lower()):
            if word not in _STOPWORDS:
                words.add(word)
    return words


def slice_spec(
    spec_text: str,
    *,
    task_title: str,
    task_description: str,
    threshold: int = SPEC_SLICE_THRESHOLD_CHARS,
) -> str:
    """Whole SPEC when short; relevant sections when long."""
    if len(spec_text) <= threshold:
        return spec_text
    matches = list(_SECTION_HEADING.finditer(spec_text))
    if not matches:
        return spec_text[:threshold].rstrip() + "\n… (SPEC truncated)"
    preamble = spec_text[: matches[0].start()].rstrip()
    sections: list[tuple[str, str]] = []
    for index, match in enumerate(matches):
        end = (
            matches[index + 1].start()
            if index + 1 < len(matches) else len(spec_text)
        )
        sections.append((match.group(1).strip(), spec_text[match.start():end].rstrip()))
    keywords = _keywords(task_title, task_description)
    chosen: list[tuple[str, str]] = []
    budget = threshold - len(preamble)
    for index, (heading, body) in enumerate(sections):
        haystack = (heading + " " + body[:600]).lower()
        score = sum(1 for word in keywords if word in haystack)
        if index == 0 or score > 0:
            if len(body) <= budget:
                chosen.append((heading, body))
                budget -= len(body)
            elif budget > 500 and score > 0:
                # The most relevant section must not be dropped
                # just for being large: include it truncated to
                # the remaining budget instead.
                chosen.append((heading, body[:budget].rstrip() + "\n… (section truncated)"))
                budget = 0
    if not chosen:
        chosen = [sections[0]]
    parts = [preamble] if preamble else []
    parts.extend(body for _heading, body in chosen)
    omitted = len(sections) - len(chosen)
    if omitted > 0:
        parts.append(
            f"… ({omitted} SPEC section(s) not relevant to this task omitted)",
        )
    return "\n\n".join(parts)
