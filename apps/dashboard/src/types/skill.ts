import type { AgentType } from './agent';

/**
 * One project skill — a folder under the repository's `skills/` directory with a
 * SKILL.md whose frontmatter carries the description. The platform resolves the
 * skills a project enables into the run context and appends the ones that apply
 * to each agent type.
 */
export interface Skill {
  id: string;
  name: string;
  /** Frontmatter description: what the skill does and when it applies. */
  description: string;
  /** Optional one-line summary from the frontmatter. */
  digest?: string;
  /** Agent types whose system prompt gets this skill appended. */
  appliesTo: AgentType[];
  /** Stack skills (java/spring/python/react) only apply to projects on that stack. */
  stackOnly: boolean;
  /** Where the definition lives, for the operator's reference. */
  path: string;
}
