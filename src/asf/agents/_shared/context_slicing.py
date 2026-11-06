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
_HAYSTACK_CHARS = 600
_MIN_TRUNCATED_BUDGET = 500

_MILESTONE_HEADING = re.compile(r"^###\s+(M\d+):\s*(.+)$", re.MULTILINE)
_SECTION_HEADING = re.compile(r"^##\s+(.+)$", re.MULTILINE)
_WORD = re.compile(r"[a-z0-9]{4,}")
_STOPWORDS = {
    "this",
    "that",
    "with",
    "from",
    "must",
    "should",
    "when",
    "then",
    "than",
    "into",
    "have",
    "will",
    "each",
    "such",
    "other",
    "about",
    "which",
    "their",
    "there",
    "these",
    "those",
    "using",
    "used",
}


def slice_plan(plan_text: str, milestone_ref: str | None) -> str:
    """PLAN preamble + the referenced milestone's block only."""
    if not milestone_ref:
        return plan_text
    matches = list(_MILESTONE_HEADING.finditer(plan_text))
    if not matches:
        return plan_text
    target = next(
        (match for match in matches if match.group(1) == milestone_ref),
        None,
    )
    if target is None:
        return plan_text
    preamble = plan_text[: matches[0].start()].rstrip()
    end = _block_end(plan_text, matches, target)
    block = plan_text[target.start() : end].rstrip()
    others = _other_milestones(matches, milestone_ref)
    parts = [preamble, block]
    if others:
        parts.append("Other milestones (not part of this task): " + "; ".join(others))
    return "\n\n".join(part for part in parts if part)


def _other_milestones(matches: list[re.Match[str]], milestone_ref: str) -> list[str]:
    return [
        f"{match.group(1)} — {match.group(2).strip()}"
        for match in matches
        if match.group(1) != milestone_ref
    ]


def _block_end(plan_text: str, matches: list[re.Match[str]], target: re.Match[str]) -> int:
    for match in matches:
        if match.start() > target.start():
            return match.start()
    # The target is the last milestone: a following '## ' section
    # (if any) is not part of its block.
    following = _SECTION_HEADING.search(plan_text, target.end())
    if following:
        return following.start()
    return len(plan_text)


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
    sections = _sections(spec_text, matches)
    keywords = _keywords(task_title, task_description)
    chosen = _choose_sections(sections, keywords, threshold - len(preamble))
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


def _sections(spec_text: str, matches: list[re.Match[str]]) -> list[tuple[str, str]]:
    sections: list[tuple[str, str]] = []
    for index, match in enumerate(matches):
        end = matches[index + 1].start() if index + 1 < len(matches) else len(spec_text)
        sections.append((match.group(1).strip(), spec_text[match.start() : end].rstrip()))
    return sections


def _choose_sections(
    sections: list[tuple[str, str]], keywords: set[str], budget: int
) -> list[tuple[str, str]]:
    chosen: list[tuple[str, str]] = []
    for index, (heading, body) in enumerate(sections):
        entry = (index, heading, body)
        picked, budget = _pick_section(entry, keywords, budget)
        if picked is not None:
            chosen.append(picked)
    return chosen


def _pick_section(
    entry: tuple[int, str, str],
    keywords: set[str],
    budget: int,
) -> tuple[tuple[str, str] | None, int]:
    index, heading, body = entry
    haystack = (heading + " " + body[:_HAYSTACK_CHARS]).lower()
    score = sum(1 for word in keywords if word in haystack)
    if index != 0 and score == 0:
        return None, budget
    if len(body) <= budget:
        return (heading, body), budget - len(body)
    if budget > _MIN_TRUNCATED_BUDGET and score > 0:
        # The most relevant section must not be dropped just for
        # being large: include it truncated to the remaining budget.
        truncated = body[:budget].rstrip() + "\n… (section truncated)"
        return (heading, truncated), 0
    return None, budget
