# AI Software Factory - Project Summary

> **Dự án:** AI Software Factory - Nền tảng tái sử dụng, độc lập dự án cho việc chạy một đội ngũ phát triển phần mềm AI
> **Trạng thái hiện tại:** Phase 8 hoàn thành (Teams Workflows approval), đang ở branch `phase-9`
> **Ngày cập nhật:** 2026-11-03

---

## 1. Tổng quan dự án

**AI Software Factory (ASF)** là một nền tảng **project-independent** (độc lập dự án) để vận hành một đội ngũ phát triển phần mềm dựa trên AI. Các dự án thực tế "gắn" vào nền tảng này thông qua **project profiles** trong thư mục `projects/`; trong khi agents, workflows và infrastructure vẫn giữ nguyên generic.

### Mục tiêu cốt lõi
- Tự động hóa quy trình phát triển phần mềm từ **Requirement → Spec → Plan → Task → Implement → Review → Test → CI → Merge**
- Tách biệt rõ ràng giữa **logic nghiệp vụ** (agents) và **orchestration/approval** (platform)
- Cho phép swap các external services (GitLab ↔ GitHub, Teams ↔ Slack, Gemini ↔ OpenAI) chỉ bằng cách thay adapter

### Luồng làm việc mục tiêu (Target Workflow)

```text
Requirement → Spec → [Approval] → Plan → [Approval] → Task → [Approval]
                                  → Implement → Code Review → Test → Quality Gate
                                  → Git host → CI → Merge
```
> **Lưu ý:** Rejections (từ chối) quay lại agent tạo ra artifact đó kèm feedback để sửa đổi.

---

## 2. Kiến trúc tổng thể

### 2.1 Nguyên tắc thiết kế (Design Rules)
1. `src/asf/`, `contracts/`, `skills/`, `workflows/` **không bao giờ** tham chiếu đến một dự án cụ thể
2. Agents **không bao giờ** gọi trực tiếp lẫn nhau; **Orchestrator** trung gian qua artifacts + approvals
3. Human approval là **platform capability**, không phải phần của agent nào
4. External services sống trong `src/asf/integrations/` và `src/asf/models/providers/` đằng sau interfaces
5. **Không LLM provider nào được hard-code**
6. Agents **không thực hiện side effects** (shell, git, network, filesystem, database) trực tiếp. Chỉ hoạt động qua ports trong `contracts/ports.md`
7. Configuration không chứa secret values; credentials được reference qua environment variables
8. State machine là **pure** (no I/O, no clock); stage lists được generate từ workflow definitions
9. Time và identifiers được inject: engines và agents không tự đọc clock hay generate IDs

### 2.2 Cấu trúc thư mục chính

```
ai-software-factory/
├── src/asf/                      # Core Python package ("asf")
│   ├── orchestrator/             # Agent sequencing & workflow progression
│   ├── workflow/                 # Declarative workflow definitions
│   ├── state_machine/            # Item states & legal transitions
│   ├── approval/                 # Human review service
│   ├── evaluation/               # Metrics recording
│   ├── configuration/            # Configuration models & loaders
│   ├── agents/                   # Specialized agent implementations (7 agents)
│   ├── integrations/             # External service adapters (GitLab, Teams, CI)
│   ├── models/                   # Model gateway & LLM provider adapters
│   ├── contracts/                # Python schema bindings
│   ├── tools/                    # Agent tool execution adapters
│   ├── execution/                # Process runners & isolation sandboxes
│   ├── storage/                  # Repository persistence adapters
│   ├── api/                      # REST / streaming endpoints
│   └── cli/                      # CLI commands
├── contracts/                     # Language-neutral JSON Schemas & ports
├── apps/dashboard/               # Control Tower frontend (React + TS + Vite)
├── skills/                       # Reusable knowledge packages
├── workflows/                    # Declarative workflow definitions (YAML)
├── templates/                    # Artifact templates (SPEC, PLAN, TASK, etc.)
├── projects/                     # Project profiles (YAML)
├── config/                       # Configuration definitions
├── harness/                      # Harness² research & offline evaluation
├── tests/                        # Unit & integration tests
├── docs/                         # Architecture documentation
├── scripts/                      # Developer & operations scripts
└── docker/                       # Container images & deployment configs
```

---

## 3. Các Phase đã triển khai

### Phase 1-5: Foundation (Đã hoàn thành trước)
- Core contracts, state machine, approval engine, configuration, base agent architecture
- SpecAgent, PlanAgent, TaskAgent cơ bản

### Phase 6: Local Orchestrator Core ✅ **HOÀN THÀNH** (Commit: `73b9b5c`)

**Mô tả:** Triển khai orchestration core đồng bộ cục bộ với SQLite persistence.

**Các khả năng chính:**
| Tính năng | Mô tả |
|-----------|-------|
| **Dispatch & Artifact Routing** | Registry, exact consumed types, isolated requests/results |
| **Durable Restart** | SQLite checkpoints với full artifacts/results/progress |
| **Approval Atomicity** | Store-owned ApprovalRepository + execution transaction |
| **Crash Recovery** | In-flight marker trước dispatch; từ chối replay tự động |
| **Bounded Retries** | Step retryPolicy, retryable/error-code checks, persisted deadline |
| **Escalation Resume** | RESUME transition + trusted operator reason |
| **Task Items** | Bounded topological order; per-item final artifacts |
| **Fix Loop** | Review/Test failures → Fix → Review → Test (max 3 cycles) |
| **Events & Metrics** | Durable outbox + injected write-side ports |

**Kết quả test:** 1,027 tests passed, 404 subtests; **97% statement coverage**
- mypy strict: ✅ | Ruff: ✅ | Bandit: ✅

**Quyết định quan trọng được user xác nhận:**
1. SQLite local persistence (stdlib, no new dependency)
2. Tối đa 3 Fix cycles tự động per task item trước khi escalate
3. Execute items sequentially theo dependsOn, mỗi CODE relative to original baseRef (KHÔNG accumulate workspace)

**Giới hạn Phase 6:**
- ❌ No live-chain claim (tất cả model/repo/sandbox operations đều fake-backed)
- ❌ No cumulative workspace (dependsOn chỉ order execution)
- ❌ No aggregate CI changeset
- ❌ Single synchronous local worker
- ❌ Phase 8/9/10 (GitLab/CI/Teams, dashboard, metrics) vẫn riêng biệt

### Phase 7: Code Agents (C3-C5) ✅ **HOÀN THÀNH** (Commit: `2b22a2d`)

**Mô tả:** Triển khai 3 agents còn lại: ReviewAgent, TestAgent, FixAgent.

**7 Agents hoàn chỉnh:**
| Agent | Trạng thái | Đặc điểm chính |
|-------|------------|----------------|
| **SpecAgent** | ✅ | Requirement → SPEC (7-section template), revision flow |
| **PlanAgent** | ✅ | SPEC → PLAN với milestone validation |
| **TaskAgent** | ✅ | SPEC+PLAN → TASK breakdown, strict JSON validation |
| **ImplementAgent** | ✅ | SPEC+PLAN+TASK → CODE (ChangeSet), secret checks |
| **ReviewAgent (C3)** | ✅ | CODE → CODE_REVIEW, 100 findings max, verdict validation |
| **TestAgent (C4)** | ✅ | **Deterministic** - không call LLM, chạy sandbox commands từ project config |
| **FixAgent (C5)** | ✅ | Review/Test failures → replacement CODE (complete ChangeSet), version++ |

**Shared Runtime (cùng dùng):**
- AgentExecutionError với error codes chuẩn
- Preflight REJECTED errors = no artifacts/events
- Shared input validation (task identity, artifact versions, context sizes, CODE validity)
- Shared codegen helpers (validation, secret reporting)

**Kết quả test:** 920 tests passed (+212 mới), 404 subtests; **98% statement coverage**
- 94 Review tests | 64 Test tests | 51 Fix tests | 3 integration chain tests

**C2 Differences retained (giữ lại theo quyết định user):**
1. ImplementAgent oversized-base = INTEGRATION_UNAVAILABLE (không phải REJECTED/VALIDATION_FAILED)
2. ImplementAgent repository failure = INTEGRATION_UNAVAILABLE (không phải REPOSITORY_ERROR)

### Phase 8: Teams Workflows Approval ✅ **HOÀN THÀNH** (Commit: `68a9ce0`)

**Mô tả:** Triển khai approval qua **Microsoft Teams Workflows / Power Automate** - **KHÔNG custom bot**.

**Kiến trúc no-custom-bot:**
- Không đăng ký Teams bot, không hosted bot, không Bot Framework endpoint, không bot SDK
- Sử dụng HTTP trigger → Adaptive Card → Wait for Response → Callback đến ASF

**Luồng đã verify offline:**
1. SpecAgent tạo SPEC v1
2. Dispatcher gửi Adaptive Card đầy đủ SPEC
3. Flow callback **Reject** kèm comment bắt buộc
4. Orchestrator pass SPEC v1 + feedback → SpecAgent
5. SpecAgent tạo SPEC v2; card mới tự động gửi
6. Card cũ **không thể** approve v2
7. **Approve v2** → tự động dispatch PlanAgent
8. PLAN reference SPEC v2 → demo COMPLETED

**Authentication & Security:**
- Flow trigger URL = credential (env-only, HTTPS/443, exact hostname pinning)
- Callback secret ≥32 chars, constant-time comparison
- Flow phải attest Entra object ID từ Teams connector (KHÔNG dùng card identity)
- ASF bind attestation → configured tenant/team/channel + mapped reviewer
- **ASF không validate Microsoft user JWT trực tiếp**
- Signed-URL/legacy Anyone HTTP triggers (OAuth token acquisition = future work)

**Kết quả test:** 1,098 tests passed (+71 Teams tests), 404 subtests; **96% coverage**
- End-to-end test: `test_authenticated_reject_rewrites_spec_then_approve_automatically_runs_plan`

**Setup thủ công cần thiết (User phải tự làm):**
1. Tạo Power Automate Flow với HTTP trigger protected URL
2. Immediate Response 202 → Post Adaptive Card and Wait for Response
3. Resolve Entra object ID từ Teams connector output
4. POST decision đến ASF callback với secret riêng, Secure Inputs/Outputs enabled

**Chưa hoàn thành Phase 8:** GitLab & CI Gate (deferred)

---

## 4. Workflow Definition (software-development.yaml)

Workflow mặc định được định nghĩa trong `workflows/software-development.yaml`:

| Step ID | Name | Type | Stage | Agent | Approval | Consumes | Produces |
|---------|------|------|-------|-------|----------|----------|----------|
| `spec` | Write specification | AGENT | SPEC | spec | ✅ | - | SPEC |
| `plan` | Write plan | AGENT | PLAN | plan | ✅ | SPEC | PLAN |
| `task` | Break down tasks | AGENT | TASK | task | ✅ | SPEC, PLAN | TASK |
| `implement` | Implement | AGENT | IMPLEMENTING | implement | ❌ | SPEC, PLAN, TASK | CODE |
| `review` | Review code | AGENT | CODE_REVIEW | review | ❌ | SPEC, PLAN, TASK, CODE | CODE_REVIEW |
| `test` | Run tests | AGENT | TESTING | test | ❌ | TASK, CODE | TEST_REPORT |
| `ci` | Run pipeline | INTEGRATION | CI | - | ❌ | CODE | - |
| `merge` | Await merge | SYSTEM | READY_TO_MERGE | - | ❌ | CODE_REVIEW, TEST_REPORT | - |

**Đặc điểm:** Dynamic stage generation từ workflow definition (không hard-code). Các step có `requiresApproval: true` sẽ generate stages: `S_DRAFT`, `S_REVIEW`, `S_REJECTED`, `S_APPROVED`, `S_ESCALATED`.

---

## 5. Agent Architecture Chi tiết

### 5.1 BaseAgent & Lifecycle
```python
# Two-stage lifecycle
1. validate(request: AgentRequest) -> ValidationResult  # Pre-execution validation
2. execute(request: AgentRequest) -> AgentResult        # Execution + metrics + events
```

**Injected Runtime (constructor injection):**
- `clock` - thời gian (không dùng system time trực tiếp)
- `id_generator` - ID generation
- `model_gateway` - LLM access (port interface)
- `event_publisher` - optional, cho ActivityEvent

### 5.2 Agent Request/Result Contract
- **AgentRequest**: standardized input với artifacts, feedback, context, config
- **AgentResult**: execution status, output artifacts, activity events, RunMetrics
- **ActivityEvent**: transport-neutral activity record (project/task/workflow/agent IDs)

### 5.3 Artifact Types (Templates trong `templates/`)
- `SPEC` - Specification (7-section template)
- `PLAN` - Implementation plan with milestones
- `TASK` - Task breakdown with items & dependencies
- `CODE` - ChangeSet (files, diffs, baseRef)
- `CODE_REVIEW` - Review findings + verdict (APPROVE/CHANGES_REQUESTED)
- `TEST_REPORT` - Test commands, results, verdict (PASS/FAIL)

---

## 6. Integration Architecture (Ports & Adapters)

### 6.1 Core Ports (định nghĩa trong `contracts/ports.md`)
- **ModelGateway** - LLM provider abstraction
- **SourceControl** - Git operations (GitLab, GitHub, etc.)
- **CiProvider** - CI/CD pipeline (GitLab CI, GitHub Actions, etc.)
- **SandboxPort** - Code execution isolation
- **RepositoryPort** - File/repository access
- **ApprovalPort** - Human approval integration
- **EventPublisher** - Activity event streaming
- **MetricsSink** - Metrics delivery

### 6.2 Adapters đã có / đang phát triển
| Integration | Adapter | Trạng thái |
|-------------|---------|------------|
| **Teams Workflows** | `src/asf/integrations/teams/` | ✅ Phase 8 done |
| **GitLab** | `src/asf/integrations/gitlab/` | 🚧 Planned |
| **CI Gateway** | `src/asf/integrations/ci/` | 🚧 Planned |
| **Gemini Gateway** | `src/asf/models/providers/gemini/` | ✅ Fake + real opt-in |
| **Scripted/Fake Gateway** | `src/asf/models/providers/scripted/` | ✅ Testing |

---

## 7. Configuration & Project Profiles

### 7.1 Hierarchical Config Resolution
```
Built-in defaults < config/platform.yaml < config/platform.local.yaml
```
- Mappings merge recursively
- Lists & scalars replaced by higher priority
- Config dir: explicit arg > `ASF_CONFIG_DIR` > `./config`

### 7.2 Project Profiles (`projects/<id>.yaml`)
- Map 1:1 với `Project` data contract
- Capture: repository provider, technology, workflow, enabled skills, project-specific config
- **Credentials:** chỉ store `{env: VAR_NAME}` references, resolved bởi adapters tại runtime

### 7.3 Skills (`skills/`)
- Knowledge packages: java, spring, react, python, git, testing, security...
- Projects enable/disable; orchestrator resolve enabled skills per agent run

---

## 8. Dashboard (Control Tower) - `apps/dashboard/`

**Tech Stack:** React + TypeScript + Vite (single-page app)

**Architecture:**
```
Dashboard (pages, features, components)
    ↓
Frontend Services (services/<domain>)
    ↓
API Contract (FactoryApi + src/types)
    ↓
AI Software Factory Backend (REST + real-time events + metrics)
```

**Current State:**
- Mock API (`mockApi`) cho UI development
- REST skeleton (`httpApi`) sẵn sàng, enable by `VITE_API_BASE_URL`
- Real-time: `FactoryApi.subscribeActivity` (SSE/WebSocket ready)
- Health Score per agent (success, approval, CI, test, revision count)

**Separation rationale:**
- Khác release cadence, runtime (browser), audience
- `src/asf/` không depend UI concerns
- UI replaceable without touching engine
- Dashboard chỉ display state + send commands (approval decisions, config changes)

---

## 9. Testing & Quality Gates

### 9.1 Test Structure
```
tests/
├── unit/           # Unit tests per module
├── integration/    # Cross-module, fake-driven chains
└── (platform tests separate from agent evaluation)
```

### 9.2 Quality Gates (chạy trước khi merge)
```powershell
# Full test suite
.\.venv\Scripts\python.exe -m pytest tests\ -x -q

# Type checking
.\.venv\Scripts\python.exe -m mypy src\ --strict

# Linting
.\.venv\Scripts\python.exe -m ruff check src\ tests\

# Security scan
.\.venv\Scripts\python.exe -m bandit -r src\

# TODO/FIXME check
rg -n 'TODO|FIXME' src\asf\agents\implement src\asf\orchestrator -g '*.py'
```

### 9.3 Current Test Stats
| Phase | Tests | Subtests | Coverage |
|-------|-------|----------|----------|
| Phase 6 | 107 | 404 | 97% |
| Phase 7 C3-C5 | 212 | 404 | 98% |
| Phase 8 Teams | 71 | 404 | 96% |
| **Total** | **1,098** | **404** | - |

---

## 10. Trạng thái hiện tại & Next Steps

### ✅ Đã hoàn thành (Phase 1-8 core)
- Core platform: contracts, state machine, approval engine, configuration
- 7 agents đầy đủ: Spec, Plan, Task, Implement, Review, Test, Fix
- Local orchestrator: SQLite checkpoints, retries, approval/revision, Fix loops
- Teams Workflows approval (no custom bot)
- Fake-driven test coverage > 1000 tests, strict typing, zero lint/security issues

### 🚧 Còn lại (Phase 8 remaining + Phase 9-10)
| Phase | Scope | Trạng thái |
|-------|-------|------------|
| **Phase 8 (remaining)** | GitLab adapter, CI Gate adapter | 📋 Planned |
| **Phase 9** | Distributed execution, job queue, multi-worker, HA | 📋 Planned |
| **Phase 10** | Dashboard backend API, real-time events, aggregate metrics/evaluation, Harness² | 📋 Planned |

### 🔑 Key Gaps để Production-Ready
1. **Real repository/sandbox adapters** - hiện tại chỉ fake
2. **Cumulative workspace** - multi-item tasks không share generated files
3. **GitLab/CI/Teams live validation** - chưa test với real services
4. **Distributed execution** - single process, SQLite write transaction blocks
5. **OAuth Flow triggering** - hiện tại dùng signed-URL/legacy Anyone
6. **Delivery retry/deduplication** - at-least-once, manual restart on failure
7. **Backend-connected dashboard** - hiện tại chỉ mock API
8. **Security audit** - historical secret-scanning/push-protection chưa resolve

---

## 11. Cách chạy & Verify (Reviewer Commands)

### Offline verification (fake-driven, no API calls):
```powershell
# Phase 6 orchestrator tests
.\.venv\Scripts\python.exe -m pytest tests\unit\test_orchestrator*.py tests\integration\test_orchestrator*.py -v

# Phase 7 agents tests
.\.venv\Scripts\python.exe -m pytest tests\unit\test_review_agent.py tests\unit\test_test_agent.py tests\unit\test_fix_agent.py tests\integration\test_code_agent_chain.py -v

# Phase 8 Teams tests
.\.venv\Scripts\python.exe -m pytest tests\unit\test_teams_approval.py tests\unit\test_teams_workflow.py tests\unit\test_teams_demo.py -q

# Full regression
.\.venv\Scripts\python.exe -m pytest tests\ -x -q
.\.venv\Scripts\python.exe -m mypy src\ --strict
.\.venv\Scripts\python.exe -m ruff check src\ tests\
.\.venv\Scripts\python.exe -m bandit -r src\
```

### Live demo (cần setup Teams Flow + HTTPS proxy):
```powershell
# Deterministic model, real Teams delivery
.\.venv\Scripts\python.exe -m asf.integrations.teams.demo --send

# Real Gemini + Teams (opt-in explicit)
.\.venv\Scripts\python.exe -m asf.integrations.teams.demo --send --gemini --requirement "YOUR_REQUIREMENT"
```

**Acceptance criteria live demo:**
- Receive SPEC v1 → Reject with comment → Receive SPEC v2
- Old card cannot approve v2 → Approve v2 → PLAN runs automatically
- Repeat-vote, missing-comment, wrong-reviewer, expired-card must NOT advance workflow

---

## 12. Tài liệu tham khảo chính

| File | Mô tả |
|------|-------|
| `README.md` | Project overview, layout, design rules, dev checks |
| `docs/architecture/README.md` | Architecture overview (13 sections) |
| `docs/architecture/phase-7-code-agents.md` | Phase 7 design decisions |
| `docs/PHASE_6_REPORT.md` | Phase 6 implementation & verification report |
| `docs/PHASE_7_C3_C5_REPORT.md` | Phase 7 C3-C5 implementation & verification report |
| `docs/PHASE_8_TEAMS_REPORT.md` | Phase 8 Teams Workflows approval report |
| `src/asf/orchestrator/README.md` | Orchestrator public API, usage, recovery, limits |
| `src/asf/storage/README.md` | SQLite lifecycle, transaction, data-retention |
| `src/asf/agents/README.md` | Implemented agents, deterministic testing, expected errors |
| `src/asf/integrations/teams/README.md` | Teams Workflows setup guide, trust boundary, limitations |
| `workflows/software-development.yaml` | Default workflow definition |
| `contracts/ports.md` | Language-neutral ports specification |
| `contracts/schemas/contracts.schema.json` | JSON Schema Draft 2020-12 contracts |

---

## 13. Kết luận

**AI Software Factory** đã xây dựng được **core platform hoàn chỉnh** cho việc điều phối các AI agents trong quy trình phát triển phần mềm, với:

- **Architecture sạch**: Tách biệt rõ platform vs project, agents vs orchestrator, core vs integrations
- **Testability cao**: 1000+ fake-driven tests, strict typing, zero lint/security issues
- **Extensibility**: Ports & adapters cho LLM, Git, CI, Approval, Sandbox - swap được mà không đổi core
- **Approval as platform capability**: Human-in-the-loop qua Teams Workflows (no custom bot)

**Tuy nhiên:** Đây vẫn là **core library implementation**, chưa phải production-ready system. Các integration adapters thực sự (GitLab, CI, real sandbox), distributed execution, backend dashboard, và operational hardening (HA, security audit, secret management) là công việc Phase 9-10.

> **Branch hiện tại:** `phase-9` - sẵn sàng cho Phase 9 development (distributed execution, job queue, multi-worker)