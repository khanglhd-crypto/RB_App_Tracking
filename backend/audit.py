"""
Ghi lại lịch sử chỉnh sửa (audit log) — ai làm gì, khi nào, trên module nào.

Dùng bởi mọi endpoint có hành động ghi (tạo/sửa/xóa/xuất phiếu) để admin
xem lại ở trang Cài Đặt (GET /api/audit-log.php trong api/audit.py).

Người dùng hiện tại được lấy từ header "X-Username", do apiPost() ở mỗi
trang frontend tự gắn vào (đọc từ localStorage.user.username).

Lưu trữ: mỗi lượt ghi log là 1 file JSON riêng trong collection "audit_log"
(xem database/filestore.py).
"""

from datetime import datetime

from flask import request

from database import filestore

COLLECTION = "audit_log"


def log_action(module, action, target="", detail=""):
    """Ghi 1 dòng lịch sử. Không bao giờ raise — lỗi ghi log không được
    làm hỏng thao tác chính (save/delete/...) đang diễn ra."""
    username = request.headers.get("X-Username") or "unknown"
    try:
        new_id = filestore.new_id()
        filestore.save_record(COLLECTION, new_id, {
            "id": new_id,
            "username": username,
            "module": module,
            "action": action,
            "target": (target or "")[:255],
            "detail": (detail or "")[:500],
            "created_at": datetime.now().isoformat(),
        })
    except OSError:
        pass
