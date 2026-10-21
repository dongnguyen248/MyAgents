# workflows/

## Purpose
This directory contains declarative, project-independent workflow definitions for the AI Software Factory.

## Guidelines
1. **Data only**: Files in this folder are declarative YAML documents (`*.yaml`, `*.yml`). They contain definitions only, not code or execution state.
2. **Project-independent**: Workflows defined here are generic pipelines (such as software development, bug fixing, or refactoring) that can be reused across any project. They must never reference specific projects, repositories, or organizations.
3. **No secrets**: Workflows contain no credentials, tokens, or secret keys.
4. **Loading**: Workflows are loaded using `asf.workflow.load_workflow(path)` or `asf.workflow.load_workflows("workflows")`.

## Existing Workflows
- `software-development.yaml`: The reference 8-step software development pipeline spanning specification, planning, task breakdown, implementation, code review, testing, CI, and merge preparation.
