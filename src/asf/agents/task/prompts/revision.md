You are revising an existing task breakdown based on human reviewer feedback.

Revision instructions:
1. Carefully address every item of reviewer feedback provided.
2. Update the relevant tasks to resolve all requested changes and rejections.
3. Keep parts of the task breakdown that are unchanged stable and consistent with previous versions.
   Preserve task IDs and titles where possible for unchanged tasks.
4. Maintain the strict task format:
   - IDs: T1, T2, ... (sequential numeric, T10 after T9)
   - milestoneRef: non-decreasing in task order, references existing PLAN milestones
   - dependsOn: only existing lower-numbered tasks; no self-dependencies
   - Cross-milestone: My must be ancestor of Mx per PLAN dependencies
   - expectedFiles: relative paths, no drive letters, no "..", no backslashes, no empty segments
   - acceptanceCriteria: non-empty list of non-empty strings
5. The Linked SPEC and Linked PLAN sections must continue to reference the original artifact IDs and versions.
6. Do not invent requirements outside the SPEC and PLAN.
7. Return ONLY the JSON envelope {"tasks": [...]} — no prose, no markdown, no code fences.