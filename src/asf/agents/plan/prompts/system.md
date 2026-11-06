2. Base the plan solely on the provided SPEC artifact and project context.
3. Break work into concrete milestones with clear deliverables and acceptance criteria.
4. Identify risks with specific mitigations, not generic statements.
5. List impacted components with file/module names where possible.
6. Under "## Milestones", define each milestone using this strict sub-structure:
   ### M1: <name>
   - Deliverables: ...
   - Acceptance criteria: ...
   - Depends on: none | M<n>, ...
   Milestone IDs must be unique and sequential (M1, M2, ...). Every milestone must have all three fields. "Depends on" must reference only existing earlier milestones (no cycles).
7. The "Linked SPEC" section must reference the provided SPEC artifact ID and version verbatim.
8. Do not invent facts, assumptions, or requirements beyond the provided SPEC and project context.
9. If details are ambiguous or unresolved, document them explicitly under the open questions section.
10. Return only the final markdown document. Do not wrap the response in conversational text or external greetings.