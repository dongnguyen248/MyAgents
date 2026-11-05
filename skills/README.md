# skills/

Reusable knowledge/instruction packages, in the open **Agent Skills**
format (agentskills.io): one folder per skill, each holding a
`SKILL.md` whose YAML frontmatter carries `name` (matching the
folder) and a `description` stating what the skill does and when it
applies, followed by the instruction body. Skills describe *how to
do things*; they never contain project specifics — project-specific
standards live in the project's review rules instead.

## How ASF uses them

A project enables skills in its profile:

```yaml
enabledSkills: [java, spring, git, testing, security]
```

At run start the assembly resolves each enabled skill's `SKILL.md`
body (frontmatter stripped) into the run context; an enabled skill
whose file cannot be read fails the run start loudly. Each agent's
prompt builder then appends the skills that apply to that agent —
activation is the platform's job, since ASF agents do not browse a
filesystem or self-select skills. Editing a `SKILL.md` changes agent
behaviour on the next run, exactly like editing a rule file.

Which skills apply to which agent is defined in
`src/asf/agents/_shared/skills.py` (`SKILL_AGENTS`) and surfaced on
the dashboard's agent pages:

| Skill | Spec | Plan | Task | Implement | Review | Fix | Test |
|---|---|---|---|---|---|---|---|
| general | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | |
| software-development | | ✓ | ✓ | ✓ | ✓ | ✓ | |
| code-review | | | | | ✓ | ✓ | |
| testing | | | ✓ | ✓ | ✓ | ✓ | ✓ |
| security | ✓ | | | ✓ | ✓ | ✓ | |
| git | | | | ✓ | | ✓ | |
| database | | ✓ | | ✓ | ✓ | ✓ | |
| java / spring / python / react | | ✓ | | ✓ | ✓ | ✓ | |

(The Test agent runs no model, so its skills never enter a prompt;
the entry exists for display and future use.)

## Authoring rules

- Keep the body tight and imperative — checklists over prose. The
  body is injected into system prompts, so every line costs tokens
  on every applicable call.
- The `description` must say what the skill does *and* when it
  applies; it is the catalogue entry humans and tooling route by.
- Keep `name` equal to the folder name (lowercase, hyphens).
- Put detail that only some tasks need into the skill body only
  when it earns its tokens; otherwise leave it out.
