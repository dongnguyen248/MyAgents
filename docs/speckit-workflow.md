# Quy trình làm việc với Spec Kit trong MyAgents

Tài liệu hướng dẫn ngắn để dùng GitHub Spec Kit (`specify-cli`) hằng ngày trên Windows + PowerShell + Antigravity IDE.

## 1. Các lệnh trong Antigravity

Khi chạy `specify init --integration agy`, Spec Kit cài các skill vào `.agents/skills/speckit-*/SKILL.md`. Trong Antigravity, các lệnh có dạng **gạch nối** (`-`):

| Lệnh | Mục đích |
|---|---|
| `/speckit-constitution` | Cập nhật nguyên tắc dự án (`.specify/memory/constitution.md`) |
| `/speckit-specify` | Tạo hoặc cập nhật `specs/NNN-<ten>/spec.md` |
| `/speckit-plan` | Tạo hoặc cập nhật `specs/NNN-<ten>/plan.md` |
| `/speckit-tasks` | Sinh hoặc cập nhật `specs/NNN-<ten>/tasks.md` |
| `/speckit-clarify` | Đặt câu hỏi làm rõ điểm mơ hồ trước khi lên plan |
| `/speckit-checklist` | Sinh checklist kiểm tra độ đầy đủ của spec/plan |
| `/speckit-analyze` | Kiểm tra tính nhất quán giữa `spec.md`, `plan.md`, `tasks.md` và `constitution.md` |
| `/speckit-implement` | Thực thi từng task trong `tasks.md` |
| `/speckit-converge` | Đối chiếu codebase hiện tại và bổ sung task còn thiếu |

## 2. Quy ước trạng thái trong `tasks.md`

Thống nhất 4 ký hiệu trạng thái trong mọi `specs/*/tasks.md`:

- `[ ]` **Chưa làm**: task mới hoặc đang chờ điều kiện tiên quyết.
- `[x]` **Đã xong**: đã implement và kiểm tra; **bắt buộc ghi kèm commit hash** (hoặc dải commit, ví dụ `0ab369a..e38f7a7`).
- `[~]` **Đã code nhưng chưa push**: code/test đã xong ở local (hoặc đang chờ lệnh push/merge của owner).
- `[!]` **Chờ quyết định** (ghi kèm nhãn `[NEEDS DECISION]`): có nhiều phương án hoặc chưa chốt phạm vi, agent **không được tự chọn**.

## 3. An toàn Git & Branch trên Windows

1. Bản `specify-cli v1.0.4` dùng `.specify/scripts/powershell/create-new-feature.ps1` **không tự `git checkout` hay tạo git branch**; nó chỉ tạo thư mục `specs/NNN-<ten>/`, ghi `.specify/feature.json` và đặt biến môi trường `$env:SPECIFY_FEATURE`.
2. Luôn kiểm tra đang đứng ở đúng branch trước khi sửa/commit:
   ```powershell
   git branch --show-current
   ```
3. Khi làm việc với nhiều feature song song, trỏ đúng feature hiện tại bằng PowerShell:
   ```powershell
   $env:SPECIFY_FEATURE = "004-live-map-phase2-board"
   ```
4. Tuân thủ quy tắc repo: commit từng file một (không `git add -A`), không `--amend`, không `reset`/`rebase` branch chưa push, và **không `git push` / tạo PR khi chưa có lệnh trực tiếp**.
