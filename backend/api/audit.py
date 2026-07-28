"""
Lịch sử chỉnh sửa (Audit Log) API.

Exposes:
  GET /api/audit-log.php - (trang Cài Đặt, chỉ admin dùng) danh sách các
                           thao tác tạo/sửa/xóa/xuất phiếu gần đây trên
                           toàn bộ app, mới nhất trước.
"""

from datetime import datetime

from flask import Blueprint, jsonify, request

from database import filestore

audit_bp = Blueprint("audit", __name__, url_prefix="/api")

COLLECTION = "audit_log"


@audit_bp.route("/audit-log.php", methods=["GET"])
def audit_log_list():
    try:
        limit = min(int(request.args.get("limit", 200)), 500)
    except ValueError:
        limit = 200

    rows = filestore.list_records(COLLECTION)
    rows.sort(key=lambda r: r.get("id", 0), reverse=True)
    rows = rows[:limit]

    items = [{
        "id": r["id"],
        "username": r.get("username", ""),
        "module": r.get("module", ""),
        "action": r.get("action", ""),
        "target": r.get("target") or "",
        "detail": r.get("detail") or "",
        "createdAt": _format(r.get("created_at")),
    } for r in rows]

    return jsonify({"ok": True, "items": items})


def _format(value):
    if not value:
        return ""
    try:
        return datetime.fromisoformat(value).strftime("%d/%m/%Y %H:%M:%S")
    except ValueError:
        return value
