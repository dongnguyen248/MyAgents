# ASF — Runbook: lệnh chạy từng phần (Windows / PowerShell)

Thứ tự chạy tổng thể:
**Cài đặt (1 lần) → Kiểm chứng (tests) → Harness (offline) → Backend API → Dashboard**
Phần Teams/Gemini thật là tùy chọn, làm sau cùng.

Yêu cầu máy: Python **3.12** (bản chuẩn như CI — CI là mốc tham chiếu; 3.13 cũng dùng được), Node.js 18+ (đang dùng tốt với Node 24), PowerShell.
Mở PowerShell tại thư mục gốc project (nơi có `pyproject.toml`).

---

## 0. Cài đặt — làm 1 lần duy nhất

```powershell
py -3.12 -m venv .venv   # máy chỉ có 3.13 thì dùng py -3.13
.\.venv\Scripts\Activate.ps1
python -m pip install -e ".[dev,api,mariadb]" -c requirements.lock
```

- `requirements.lock` ghim đúng version của mọi gói (kể cả ruff/mypy/bandit/pytest) — CI cài cùng một lệnh này. Sau khi pin thay đổi, xoá `.venv` và tạo lại từ đầu. Quy trình bump version dev tools: xem README, mục "Bumping the pinned dev tools".

- `dev` = pytest/ruff/mypy/bandit. `teams` = fastapi/uvicorn/httpx (backend API cần).
- Không cần cài DB server, không cần Docker (thư mục `docker/` hiện chỉ có README).

## 1. Kiểm chứng nhanh — nên chạy trước mọi thứ

```powershell
python -m pytest tests\ -q          # kỳ vọng: 1131 passed, 404 subtests
python -m ruff check src\ harness\ tests\
python -m mypy src\
python -m bandit -r src\
python -m asf                        # chỉ in version 0.1.0
```

## 2. Phase 11 — Harness (offline, không cần .env, không cần DB)

```powershell
python -m harness.evaluation.cli                       # 3 cases, in PASS/score từng case
python -m harness.evaluation.cli --out report.json     # thêm xuất report JSON
```

## 3. Phase 9 + 10 — Backend API (FastAPI + MetricsService)

### 3a. Chạy thử không cần server (headless, chứng minh pipeline chạy hết)

```powershell
python -m asf.api.demo --selftest
# kỳ vọng dòng cuối: SELFTEST OK - final stage: COMPLETED
```

### 3b. Chạy server thật

```powershell
# Cách A — chạy thật trên MariaDB (giữ run/approval qua các lần restart).
# Cần .env ở thư mục gốc repo chứa ASF_MARIADB_PASSWORD (xem mục 5):
python -m asf.api.demo --port 8000

# Cách B — chạy tạm trong RAM (không cần DB; mất HẾT run/approval khi tắt,
# chỉ để demo nhanh — server sẽ in cảnh báo to khi khởi động):
python -m asf.api.demo --port 8000 --ephemeral
```

Không có `.env`/mật khẩu MariaDB mà cũng không truyền `--ephemeral` thì
server từ chối khởi động và in hướng dẫn cấu hình — không còn store file
nào để tự rơi xuống nữa.

Kiểm tra sống: mở http://127.0.0.1:8000/health → `{"status":"ok"}`

### 3c. Điều khiển qua API (terminal PowerShell khác, server vẫn chạy)

```powershell
# Tạo run (projectId lấy từ thư mục projects\: vhpc hoặc vnpc)
curl.exe -X POST http://127.0.0.1:8000/runs -H "Content-Type: application/json" -d '{\"taskId\":\"task-1\",\"projectId\":\"vhpc\",\"inputs\":{\"spec\":{\"requirement\":\"Build a calculator\"}}}'

# Đẩy workflow 1 bước (thay <RUN_ID> bằng id trả về ở bước trên)
curl.exe -X POST http://127.0.0.1:8000/runs/<RUN_ID>/tick

# Xem approval đang chờ
curl.exe http://127.0.0.1:8000/approvals

# Duyệt (thay <APPROVAL_ID>)
curl.exe -X POST http://127.0.0.1:8000/approvals/<APPROVAL_ID>/decision -H "Content-Type: application/json" -d '{\"decision\":\"APPROVE\",\"comment\":\"ok\"}'
# decision nhận: APPROVE | REJECT | REQUEST_CHANGES | COMMENT

# Lặp tick → approvals → decision cho SPEC, PLAN, TASK cho tới khi COMPLETED:
curl.exe http://127.0.0.1:8000/workflows
curl.exe http://127.0.0.1:8000/tasks
curl.exe http://127.0.0.1:8000/agents
curl.exe http://127.0.0.1:8000/activity?limit=20
curl.exe http://127.0.0.1:8000/metrics/overview
```

## 4. Dashboard (Phase 9 — frontend nối backend thật)

Backend (phần 3b) phải chạy TRƯỚC. Terminal mới:

```powershell
cd apps\dashboard
Copy-Item .env.example .env
npm install
npm run dev          # http://localhost:5173
```

- `.env` chỉ có 1 dòng: `VITE_API_BASE_URL=http://127.0.0.1:8000`
- Không có file `.env` này → dashboard tự dùng mock data trong trình duyệt.
- Kiểm tra build: `npm run build`

## 5. Database — MariaDB là store duy nhất cho chạy thật

- Cần một server MariaDB và một tài khoản có quyền trên database của ASF,
  ví dụ (chạy bằng tài khoản root của MariaDB):
  `CREATE USER 'asf'@'127.0.0.1' IDENTIFIED BY '<mật khẩu>';`
  `GRANT ALL PRIVILEGES ON asf.* TO 'asf'@'127.0.0.1';`
  Database và bảng được store tự tạo + migrate khi mở — không cần tạo tay.
- Kết nối khai trong file `.env` ở thư mục gốc repo (đã gitignore; mẫu ở
  `.env.example`): bắt buộc có `ASF_MARIADB_PASSWORD`; các biến
  `ASF_MARIADB_HOST` / `ASF_MARIADB_PORT` / `ASF_MARIADB_USER` /
  `ASF_MARIADB_DATABASE` chỉ cần khi khác mặc định 127.0.0.1 / 3306 / asf / asf.
- Metrics (Phase 10): sống trong RAM của process backend, tắt server là reset.
  Thư viện có `snapshot()/restore()` dạng JSON nếu sau này muốn lưu ra file.
- Tests: unit test dùng `InMemoryStore` (đúng contract của store MariaDB,
  không bền qua process); hành vi MariaDB thật nằm ở
  `tests/integration/test_mariadb_store.py`, tự skip khi không đặt
  `ASF_TEST_MARIADB=1` — cách chạy bằng Docker xem `src/asf/storage/README.md`.

## 6. .env / biến môi trường — toàn cảnh

Project Python **không tự đọc file `.env`** (không dùng python-dotenv).
Biến môi trường phải set thật vào shell. Config thường thì đi qua file YAML.

| Biến / file | Dùng cho | Bắt buộc? |
|---|---|---|
| `apps/dashboard/.env` → `VITE_API_BASE_URL` | Dashboard nối backend thật | Có, nếu muốn dashboard dùng data thật |
| `ASF_CONFIG_DIR` | Đổi thư mục config mặc định (`.\config`) | Không |
| `config\platform.local.yaml` | Override config local (đã gitignore) — Teams channel/reviewer để ở đây | Chỉ khi làm Teams |
| `ASF_TEAMS_WORKFLOW_URL` | URL trigger của Power Automate Flow (chính là credential) | Chỉ khi làm Teams |
| `ASF_TEAMS_CALLBACK_SECRET` | Secret callback ASF↔Flow, ≥ 32 ký tự, không khoảng trắng | Chỉ khi làm Teams |
| `ASF_LIVE_GEMINI_API_KEY` | Gọi Gemini thật | Chỉ khi chạy Gemini live |
| `ASF_LIVE_GEMINI_MODEL` | Model id Gemini | Chỉ khi chạy Gemini live |

Set biến trong PowerShell (chỉ có hiệu lực trong cửa sổ đó):

```powershell
$env:ASF_TEAMS_WORKFLOW_URL = "https://...URL trigger của Flow..."
$env:ASF_TEAMS_CALLBACK_SECRET = "chuỗi-ngẫu-nhiên-ít-nhất-32-ký-tự"
```

File config nền: copy `config\platform.example.yaml` → `config\platform.yaml`
nếu muốn chỉnh model profile/endpoint; trong file chỉ được ghi dạng
`credentials: {env: TEN_BIEN}` — **không bao giờ ghi secret thật vào YAML**.
Bản demo API chạy được mà không cần file này (loader tự dùng defaults).

## 7. Tùy chọn — Teams demo (Phase 8, làm sau) + Gemini thật

Đã set 2 env ở phần 6 + khai channel trong `config\platform.local.yaml`
(khung YAML mẫu nằm trong `src\asf\integrations\teams\README.md`) thì:

```powershell
python -m asf.integrations.teams.demo --send                      # model giả lập, Teams thật
python -m asf.integrations.teams.demo --send --gemini --requirement "YOUR_REQUIREMENT"
```

Callback của Flow phải về được máy mày qua HTTPS công khai (cần proxy/tunnel),
server callback nghe ở port 3978 mặc định (`--port` để đổi).

Gemini smoke test riêng (1 request):

```powershell
$env:ASF_LIVE_GEMINI_API_KEY = "..."
$env:ASF_LIVE_GEMINI_MODEL = "<model id>"
python scripts\gemini_smoke.py
```
