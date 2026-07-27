"""
Ghi lại lịch sử chỉnh sửa (audit log) — ai làm gì, khi nào, trên module nào.

Dùng bởi mọi endpoint có hành động ghi (tạo/sửa/xóa/xuất phiếu) để admin
xem lại ở trang Cài Đặt (GET /api/audit-log.php trong api/audit.py).

Người dùng hiện tại được lấy từ header "X-Username", do apiPost() ở mỗi
trang frontend tự gắn vào (đọc từ localStorage.user.username) — app này
không có session/token phía server nên đây là cách duy nhất để biết ai
đang thao tác.
"""

import psycopg2
from flask import request

from database.db import get_connection


def log_action(module, action, target="", detail=""):
    """Ghi 1 dòng lịch sử. Không bao giờ raise — lỗi ghi log không được
    làm hỏng thao tác chính (save/delete/...) đang diễn ra."""
    username = request.headers.get("X-Username") or "unknown"
    try:
        connection = get_connection()
        try:
            with connection.cursor() as cursor:
                cursor.execute(
                    "INSERT INTO audit_log (username, module, action, target, detail) VALUES (%s,%s,%s,%s,%s)",
                    (username, module, action, (target or "")[:255], (detail or "")[:500]),
                )
        finally:
            connection.close()
    except psycopg2.Error:
        pass
