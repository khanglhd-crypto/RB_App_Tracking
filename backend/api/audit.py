"""
Lịch sử chỉnh sửa (Audit Log) API.

Exposes:
  GET /api/audit-log.php - (trang Cài Đặt, chỉ admin dùng) danh sách các
                           thao tác tạo/sửa/xóa/xuất phiếu gần đây trên
                           toàn bộ app, mới nhất trước.
"""

import psycopg2
from flask import Blueprint, jsonify, request

from database.db import get_connection

audit_bp = Blueprint("audit", __name__, url_prefix="/api")


@audit_bp.route("/audit-log.php", methods=["GET"])
def audit_log_list():
    try:
        limit = min(int(request.args.get("limit", 200)), 500)
    except ValueError:
        limit = 200

    try:
        connection = get_connection()
        try:
            with connection.cursor() as cursor:
                cursor.execute(
                    "SELECT * FROM audit_log ORDER BY id DESC LIMIT %s", (limit,)
                )
                rows = cursor.fetchall()
        finally:
            connection.close()
    except psycopg2.Error as err:
        return jsonify({"ok": False, "error": f"Lỗi kết nối cơ sở dữ liệu: {err}"}), 500

    items = [{
        "id": r["id"],
        "username": r["username"],
        "module": r["module"],
        "action": r["action"],
        "target": r["target"] or "",
        "detail": r["detail"] or "",
        "createdAt": r["created_at"].strftime("%d/%m/%Y %H:%M:%S") if r["created_at"] else "",
    } for r in rows]

    return jsonify({"ok": True, "items": items})
