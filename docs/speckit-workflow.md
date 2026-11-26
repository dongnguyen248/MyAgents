# Quy trình Speckit cho ASF

Tài liệu này mô tả cách dùng thư mục `specs/` trong repo. Mỗi tính
năng hoặc đợt việc có một thư mục `specs/NNN-<slug>/` gồm ba file:
`spec.md` (vấn đề, yêu cầu, tiêu chí chấp nhận), `plan.md` (cách
làm), `tasks.md` (danh sách việc để theo dõi). Số `NNN` tăng dần
theo thứ tự tạo, không tái sử dụng.

## Trạng thái

- `[ ]` chưa làm hoặc chưa duyệt.
- `[~]` đã code, chờ bước tiếp theo (thường là chờ push/merge).
- `[x]` đã xong.
- `[NEEDS DECISION]` chỉ dùng khi thật sự còn quyết định chưa chốt;
  khi đã quyết thì bỏ marker và ghi quyết định vào spec.

Trạng thái ghi ở đầu `spec.md`; tiến độ chi tiết nằm ở `tasks.md`
với checkbox `- [ ]` / `- [x]`.

## Phụ thuộc

Mỗi spec ghi rõ "Phụ thuộc" và "Chặn" ở đầu file. Chuỗi hiện tại:
S0 → S0b → PR 1 → PR 2a; PR 1b → PR 2c; C1 độc lập nhưng sau S0.
Không bắt đầu một spec khi điều kiện tiên quyết của nó chưa merge,
trừ khi Dong duyệt ngoại lệ.

## Nguồn sự thật

Khi một spec có file nguồn bên ngoài (ví dụ bản tasks gốc trong
goal workspace), `tasks.md` trong `specs/` ghi dòng "Nguồn:" ở đầu
và là bản chính để theo dõi. File nguồn không sửa. Nếu hai bên
khác nhau, báo trong báo cáo cuối, không tự chọn bên nào.

## Quy trình làm việc

1. Viết/cập nhật `spec.md` trước khi code: vấn đề, phạm vi, ngoài
   phạm vi, yêu cầu, tiêu chí chấp nhận.
2. Viết `plan.md`: cách triển khai, file chạm vào, test, gate.
3. Tách `tasks.md` thành các việc kiểm chứng được.
4. Code theo tasks; commit mỗi file một commit, message
   Conventional Commits; không `git add -A`.
5. Chạy đủ gate trước khi báo cáo: `ruff check src tests`,
   `ruff format --check src tests harness`, `mypy src --platform
   linux`, `bandit -c .bandit -r src -q`, ratchet, `pytest -q`,
   demo selftest; dashboard: `npm test`, `npm run build`, lint
   file đã đụng (đếm Rule G trước/sau).
6. Chạy phân tích nhất quán trên `specs/` (mọi thư mục đủ ba file,
   trạng thái hợp lệ, tham chiếu phụ thuộc không treo, không còn
   `[NEEDS DECISION]` sót) và dán nguyên văn kết quả.
7. Báo cáo cuối: commit, bảng audit nếu có, gate nguyên văn, mục
   "Lệch dự kiến". Không push, không tạo PR khi chưa có lệnh của
   Dong; Dong tạo và merge PR.

## Constitution

Nguyên tắc bất biến của repo nằm ở `.specify/memory/constitution.md`,
đúc từ `AGENTS.md` và `docs/architecture/README.md`. Spec và plan
phải tuân thủ constitution; xung đột thì dừng và hỏi Dong.
