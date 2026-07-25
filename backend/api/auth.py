"""
Authentication API.

Exposes:
  POST /api/login             - verifies a username/password pair against the
                                 `users` table (bcrypt-hashed) và kiểm tra
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
"""

import bcrypt
import pymysql
from flask import Blueprint, jsonify, request

from audit import log_action
from database.db import get_connection

auth_bp = Blueprint("auth", __name__, url_prefix="/api")

# Generic message for any login failure so we never reveal whether
# the username itself was the wrong part of the pair.
INVALID_CREDENTIALS_MESSAGE = "Sai tài khoản hoặc mật khẩu"

# Chỉ những email thuộc domain công ty mới được tự đăng ký tài khoản.
ALLOWED_EMAIL_SUFFIX = "@redblue.vn"

# Các loại tài khoản được phép chọn khi tự đăng ký / admin gán lại ở Cài Đặt.
# Chỉ 'Engineer' mới được xem mã AnyDesk & UltraView (test-ipc.html, on-tram.html).
ACCOUNT_TYPES = {"Engineer", "OS", "AS"}


@auth_bp.route("/login", methods=["POST"])
def login():
    data = request.get_json(silent=True) or {}
    username = (data.get("username") or "").strip()
    password = data.get("password") or ""

    if not username or not password:
        return jsonify({"success": False, "message": INVALID_CREDENTIALS_MESSAGE})

    try:
        connection = get_connection()
        try:
            with connection.cursor() as cursor:
                cursor.execute(
                    "SELECT id, fullname, role, status, password_hash FROM users WHERE username = %s",
                    (username,),
                )
                user = cursor.fetchone()
        finally:
            connection.close()
    except pymysql.MySQLError as err:
        return jsonify({
            "success": False,
            "message": f"Lỗi kết nối cơ sở dữ liệu: {err}",
        }), 500

    if user is None:
        return jsonify({"success": False, "message": INVALID_CREDENTIALS_MESSAGE})

    password_matches = bcrypt.checkpw(
        password.encode("utf-8"), user["password_hash"].encode("utf-8")
    )
    if not password_matches:
        return jsonify({"success": False, "message": INVALID_CREDENTIALS_MESSAGE})

    if user["status"] == "pending":
        return jsonify({
            "success": False,
            "message": "Tài khoản đang chờ quản trị viên duyệt (mục Cài Đặt).",
        })

    return jsonify({
        "success": True,
        "user": {
            "id": user["id"],
            "username": username,
            "fullname": user["fullname"],
            "role": user["role"],
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

    password_hash = bcrypt.hashpw(password.encode("utf-8"), bcrypt.gensalt()).decode("utf-8")

    # Loại tài khoản (Engineer/OS/AS) chỉ admin mới được chỉ định, ở Cài Đặt sau khi duyệt —
    # người tự đăng ký không được tự chọn, nên luôn tạo mới ở role mặc định 'viewer'.
    try:
        connection = get_connection()
        try:
            with connection.cursor() as cursor:
                cursor.execute(
                    "INSERT INTO users (username, password_hash, fullname, role, email, status) VALUES (%s,%s,'','viewer',%s,'pending')",
                    (username, password_hash, email),
                )
                new_id = cursor.lastrowid
        finally:
            connection.close()
    except pymysql.err.IntegrityError:
        return jsonify({
            "success": False,
            "message": f"Tài khoản \"{username}\" hoặc email \"{email}\" đã được đăng ký trước đó",
        }), 400
    except pymysql.MySQLError as err:
        return jsonify({"success": False, "message": f"Lỗi kết nối cơ sở dữ liệu: {err}"}), 500

    log_action("users", "create", target=username, detail=f"tự đăng ký, email={email}")

    return jsonify({
        "success": True,
        "message": "Đăng ký thành công, tài khoản đang chờ quản trị viên duyệt.",
        "user": {"id": new_id, "username": username, "fullname": "", "role": "viewer", "status": "pending"},
    })


@auth_bp.route("/users-list.php", methods=["GET"])
def users_list():
    try:
        connection = get_connection()
        try:
            with connection.cursor() as cursor:
                cursor.execute(
                    """SELECT id, username, email, fullname, role, status, created_at
                       FROM users ORDER BY (status = 'pending') DESC, id DESC"""
                )
                rows = cursor.fetchall()
        finally:
            connection.close()
    except pymysql.MySQLError as err:
        return jsonify({"ok": False, "error": f"Lỗi kết nối cơ sở dữ liệu: {err}"}), 500

    items = [{
        "id": r["id"],
        "username": r["username"],
        "email": r["email"] or "",
        "fullname": r["fullname"] or "",
        "role": r["role"],
        "status": r["status"],
        "createdAt": r["created_at"].strftime("%d/%m/%Y %H:%M") if r["created_at"] else "",
    } for r in rows]

    return jsonify({"ok": True, "items": items})


@auth_bp.route("/users-approve.php", methods=["POST"])
def users_approve():
    data = request.get_json(silent=True) or {}
    record_id = data.get("id")
    if not record_id:
        return jsonify({"ok": False, "error": "Thiếu id"}), 400

    try:
        connection = get_connection()
        try:
            with connection.cursor() as cursor:
                cursor.execute(
                    "UPDATE users SET status = 'active' WHERE id = %s AND status = 'pending'",
                    (record_id,),
                )
        finally:
            connection.close()
    except pymysql.MySQLError as err:
        return jsonify({"ok": False, "error": f"Lỗi kết nối cơ sở dữ liệu: {err}"}), 500

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

    try:
        connection = get_connection()
        try:
            with connection.cursor() as cursor:
                cursor.execute(
                    "UPDATE users SET role = %s WHERE id = %s AND username != 'admin'",
                    (role, record_id),
                )
        finally:
            connection.close()
    except pymysql.MySQLError as err:
        return jsonify({"ok": False, "error": f"Lỗi kết nối cơ sở dữ liệu: {err}"}), 500

    log_action("users", "update", target=str(record_id), detail=f"role={role}")
    return jsonify({"ok": True})


@auth_bp.route("/users-delete.php", methods=["POST"])
def users_delete():
    data = request.get_json(silent=True) or {}
    record_id = data.get("id")
    if not record_id:
        return jsonify({"ok": False, "error": "Thiếu id"}), 400

    deleted_username = None
    try:
        connection = get_connection()
        try:
            with connection.cursor() as cursor:
                cursor.execute("SELECT username FROM users WHERE id = %s", (record_id,))
                row = cursor.fetchone()
                if row and row["username"] == "admin":
                    return jsonify({"ok": False, "error": "Không thể xóa tài khoản admin mặc định"}), 400
                deleted_username = row["username"] if row else None
                cursor.execute("DELETE FROM users WHERE id = %s", (record_id,))
        finally:
            connection.close()
    except pymysql.MySQLError as err:
        return jsonify({"ok": False, "error": f"Lỗi kết nối cơ sở dữ liệu: {err}"}), 500

    log_action("users", "delete", target=deleted_username or str(record_id))
    return jsonify({"ok": True})
