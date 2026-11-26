# Chores

Trạng thái: [ ] các mục nhỏ độc lập, không chặn spec nào.

- Dashboard lint: `AgentConnectionFields.tsx` —
  `ConnectionKeyField` 40 dòng, vượt giới hạn 30
  (max-lines-per-function). Lỗi có từ trước trên master; sửa bằng
  cách tách component con, không sửa trong PR không liên quan.
- Gate chore: `test_workflow_view_exposes_artifact_contents` phụ
  thuộc `list_projects()[0]`; ghim project id trong test.
- Dọn `PR-DRAFT-0/1/2.md` đang được track trên master (draft cũ
  của Phase 2; PR draft không commit theo quy ước hiện tại).
- Thêm `projects/rules/languages/python.md` (language pack còn
  thiếu).
