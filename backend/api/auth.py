"""
Authentication API.

Exposes:
  POST /api/login             - verifies a username/password pair against the
                                 `users` collection (bcrypt-hashed) và kiểm tra
                                 tài khoản đã được admin duyệt (status='active')
                                 chưa, trả về hồ sơ công khai nếu hợp lệ.
  POST /api/register           - tự đăng ký tài khoản mới; chỉ chấp nhận email
                                 đuôi @redblue.vn, tạo tài khoản ở trạng thái
                                 'pending' (role mặc định 'viewer') — phải chờ
                                 admin duyệt VÀ tự tay chỉ định loại tài khoản
                                 (Engineer/OS/AS) ở Cài Đặt, người đăng ký
                                 không được tự chọn loại tài khoản.
  GET  /api/users-list.php     - (chỉ admin dùng ở trang Cài Đặt) danh sách
                                 toàn bộ tài khoản, gồm cả các tài khoản đang
                                 chờ duyệt.
  POST /api/users-approve.php  - duyệt 1 tài khoản đang chờ (status -> active)
  POST /api/users-delete.php   - xóa 1 tài khoản (dùng để từ chối tài khoản
                                 đang chờ, hoặc thu hồi quyền truy cập)
  POST /api/users-role.php     - (chỉ admin) đổi loại tài khoản (Engineer/OS/AS)

Lưu trữ: mỗi tài khoản là 1 file JSON riêng trong collection "users" (xem
database/filestore.py) — để chạy offline, đồng bộ nhiều máy qua Shared Drive.
"""

from datetime import datetime

import bcrypt
from flask import Blueprint, jsonify, request

from audit import log_action
from database import filestore

auth_bp = Blueprint("auth", __name__, url_prefix="/api")

COLLECTION = "users"

# Generic message for any login failure so we never reveal whether
# the username itself was the wrong part of the pair.
INVALID_CREDENTIALS_MESSAGE = "Sai tài khoản hoặc mật khẩu"

# Chỉ những email thuộc domain công ty mới được tự đăng ký tài khoản.
ALLOWED_EMAIL_SUFFIX = "@redblue.vn"

# Các loại tài khoản được phép chọn khi tự đăng ký / admin gán lại ở Cài Đặt.
# Chỉ 'Engineer' mới được xem mã AnyDesk & UltraView (test-ipc.html, on-tram.html).
ACCOUNT_TYPES = {"Engineer", "OS", "AS"}


def _find_by_username(username):
    return filestore.find_one(COLLECTION, lambda u: u.get("username") == username)


@auth_bp.route("/login", methods=["POST"])
def login():
    data = request.get_json(silent=True) or {}
    username = (data.get("username") or "").strip()
    password = data.get("password") or ""

    if not username or not password:
        return jsonify({"success": False, "message": INVALID_CREDENTIALS_MESSAGE})

    user = _find_by_username(username)
    if user is None:
        return jsonify({"success": False, "message": INVALID_CREDENTIALS_MESSAGE})

    password_matches = bcrypt.checkpw(
        password.encode("utf-8"), user["password_hash"].encode("utf-8")
    )
    if not password_matches:
        return jsonify({"success": False, "message": INVALID_CREDENTIALS_MESSAGE})

    if user.get("status") == "pending":
        return jsonify({
            "success": False,
            "message": "Tài khoản đang chờ quản trị viên duyệt (mục Cài Đặt).",
        })

    return jsonify({
        "success": True,
        "user": {
            "id": user["id"],
            "username": username,
            "fullname": user.get("fullname") or "",
            "role": user.get("role") or "viewer",
        },
    })


@auth_bp.route("/register", methods=["POST"])
def register():
    data = request.get_json(silent=True) or {}
    email    = (data.get("email") or "").strip().lower()
    username = (data.get("username") or "").strip()
    password = data.get("password") or ""

    if not email or not username or not password:
        return jsonify({"success": False, "message": "Vui lòng nhập đầy đủ email, tài khoản và mật khẩu"}), 400

    if not email.endswith(ALLOWED_EMAIL_SUFFIX):
        return jsonify({
            "success": False,
            "message": f"Chỉ email đuôi \"{ALLOWED_EMAIL_SUFFIX}\" mới được đăng ký tài khoản",
        }), 403

    if len(password) < 6:
        return jsonify({"success": False, "message": "Mật khẩu phải có ít nhất 6 ký tự"}), 400

    # Loại tài khoản (Engineer/OS/AS) chỉ admin mới được chỉ định, ở Cài Đặt sau khi duyệt —
    # người tự đăng ký không được tự chọn, nên luôn tạo mới ở role mặc định 'viewer'.
    existing = filestore.find_one(
        COLLECTION, lambda u: u.get("username") == username or u.get("email") == email
    )
    if existing:
        return jsonify({
            "success": False,
            "message": f"Tài khoản \"{username}\" hoặc email \"{email}\" đã được đăng ký trước đó",
        }), 400

    password_hash = bcrypt.hashpw(password.encode("utf-8"), bcrypt.gensalt()).decode("utf-8")
    new_id = filestore.new_id()
    filestore.save_record(COLLECTION, new_id, {
        "id": new_id,
        "username": username,
        "password_hash": password_hash,
        "fullname": "",
        "role": "viewer",
        "email": email,
        "status": "pending",
        "created_at": datetime.now().isoformat(),
    })

    log_action("users", "create", target=username, detail=f"tự đăng ký, email={email}")

    return jsonify({
        "success": True,
        "message": "Đăng ký thành công, tài khoản đang chờ quản trị viên duyệt.",
        "user": {"id": new_id, "username": username, "fullname": "", "role": "viewer", "status": "pending"},
    })


@auth_bp.route("/users-list.php", methods=["GET"])
def users_list():
    rows = filestore.list_records(COLLECTION)
    rows.sort(key=lambda r: (r.get("status") != "pending", -r.get("id", 0)))

    items = [{
        "id": r["id"],
        "username": r.get("username", ""),
        "email": r.get("email") or "",
        "fullname": r.get("fullname") or "",
        "role": r.get("role") or "viewer",
        "status": r.get("status") or "active",
        "createdAt": _format_created_at(r.get("created_at")),
    } for r in rows]

    return jsonify({"ok": True, "items": items})


def _format_created_at(value):
    if not value:
        return ""
    try:
        return datetime.fromisoformat(value).strftime("%d/%m/%Y %H:%M")
    except ValueError:
        return value


@auth_bp.route("/users-approve.php", methods=["POST"])
def users_approve():
    data = request.get_json(silent=True) or {}
    record_id = data.get("id")
    if not record_id:
        return jsonify({"ok": False, "error": "Thiếu id"}), 400

    user = filestore.get_record(COLLECTION, record_id)
    if user and user.get("status") == "pending":
        user["status"] = "active"
        filestore.save_record(COLLECTION, record_id, user)

    log_action("users", "update", target=str(record_id), detail="duyệt tài khoản")
    return jsonify({"ok": True})


@auth_bp.route("/users-role.php", methods=["POST"])
def users_role():
    data = request.get_json(silent=True) or {}
    record_id = data.get("id")
    role = (data.get("role") or "").strip()
    if not record_id or not role:
        return jsonify({"ok": False, "error": "Thiếu id hoặc loại tài khoản"}), 400
    if role not in ACCOUNT_TYPES:
        return jsonify({"ok": False, "error": "Loại tài khoản không hợp lệ"}), 400

    user = filestore.get_record(COLLECTION, record_id)
    if user and user.get("username") != "admin":
        user["role"] = role
        filestore.save_record(COLLECTION, record_id, user)

    log_action("users", "update", target=str(record_id), detail=f"role={role}")
    return jsonify({"ok": True})


@auth_bp.route("/users-delete.php", methods=["POST"])
def users_delete():
    data = request.get_json(silent=True) or {}
    record_id = data.get("id")
    if not record_id:
        return jsonify({"ok": False, "error": "Thiếu id"}), 400

    user = filestore.get_record(COLLECTION, record_id)
    if user and user.get("username") == "admin":
        return jsonify({"ok": False, "error": "Không thể xóa tài khoản admin mặc định"}), 400

    filestore.delete_record(COLLECTION, record_id)

    log_action("users", "delete", target=(user.get("username") if user else str(record_id)))
    return jsonify({"ok": True})
