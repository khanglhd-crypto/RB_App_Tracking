import logging
import os
import sys
import time

from flask import Flask, g, jsonify, request, send_from_directory
from flask_cors import CORS
from werkzeug.exceptions import HTTPException

from api.auth import auth_bp
from api.pillar_tests import pillar_tests_bp
from api.ipc import ipc_bp
from api.tram import tram_bp
from api.suvu import suvu_bp
from api.report_pdf import report_pdf_bp
from api.audit import audit_bp
from database import filestore
from drive_store import get_shared_sync
from logsetup import setup_logging

logger = setup_logging()
logger.info("=== Backend started (PID=%s) ===", os.getpid())


def _find_frontend_dir():
    # Khi đóng gói bằng PyInstaller (--onefile), file được giải nén tạm vào
    # sys._MEIPASS lúc chạy — frontend/ phải được include vào đó qua --add-data.
    if getattr(sys, "frozen", False) and hasattr(sys, "_MEIPASS"):
        bundled = os.path.join(sys._MEIPASS, "frontend")
        if os.path.isdir(bundled):
            return bundled
    # Chạy trực tiếp bằng "python server.py" (dev) — frontend/ nằm ngang hàng
    # với backend/ ở gốc repo.
    return os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "frontend")


# Thư mục frontend (HTML/CSS/JS tĩnh) — phục vụ luôn từ chính server Flask
# này, để app Desktop chỉ cần mở 1 cửa sổ trỏ vào localhost, không cần
# deploy/host frontend ở nơi khác.
FRONTEND_DIR = _find_frontend_dir()

app = Flask(__name__)
CORS(app)

app.register_blueprint(auth_bp)
app.register_blueprint(pillar_tests_bp)
app.register_blueprint(ipc_bp)
app.register_blueprint(tram_bp)
app.register_blueprint(suvu_bp)
app.register_blueprint(report_pdf_bp)
app.register_blueprint(audit_bp)


@app.before_request
def _log_request_start():
    g._start_time = time.time()


@app.after_request
def _log_request_end(response):
    try:
        duration_ms = int((time.time() - g._start_time) * 1000)
        # >3s là bất thường (ghi/đọc Shared Drive đang chậm) — ghi mức WARNING
        # để dễ lọc ra trong file log khi cần chẩn đoán.
        level = logging.WARNING if duration_ms > 3000 else logging.INFO
        logger.log(level, "%s %s -> %s (%sms)", request.method, request.path, response.status_code, duration_ms)
    except Exception:
        pass
    return response


@app.errorhandler(Exception)
def _log_unhandled_error(err):
    # Lỗi HTTP bình thường (404 static file, 405...) thì để Flask tự xử lý như
    # cũ — chỉ log + đổi thành JSON cho lỗi thật sự không lường trước được.
    if isinstance(err, HTTPException):
        return err
    logger.exception("Lỗi không xác định ở %s %s: %s", request.method, request.path, err)
    return jsonify({"ok": False, "error": "Lỗi máy chủ không xác định, xem log để biết chi tiết"}), 500


@app.route("/api/health")
def health():
    # "ready" chỉ true khi collection "users" đã tải xong từ Drive — Electron
    # đợi cờ này trước khi mở cửa sổ, để tránh người dùng đăng nhập ngay lúc
    # dữ liệu chưa kịp tải xong (sẽ báo nhầm "sai tài khoản hoặc mật khẩu").
    return jsonify({"status": "ok", "ready": filestore.is_ready()})


@app.route("/api/upload-electron-log.php", methods=["POST"])
def upload_electron_log():
    # main.js (Electron) gọi endpoint này mỗi 30s để đẩy log của chính nó
    # (khởi động app, có tìm thấy Shared Drive không...) lên Drive — dùng lại
    # đúng cơ chế log backend đã có (drive_store.py), không tự nói chuyện
    # với Drive từ phía Node.js nữa.
    data = request.get_json(silent=True) or {}
    filename = (data.get("filename") or "").strip()
    content = data.get("content") or ""
    if not filename:
        return jsonify({"ok": False, "error": "Thiếu tên file"}), 400
    try:
        get_shared_sync().upload_log_content(filename, content)
    except Exception as err:
        return jsonify({"ok": False, "error": str(err)}), 500
    return jsonify({"ok": True})


@app.route("/")
def serve_root():
    return send_from_directory(FRONTEND_DIR, "login.html")


@app.route("/<path:filename>")
def serve_frontend(filename):
    return send_from_directory(FRONTEND_DIR, filename)


if __name__ == "__main__":
    # App chạy offline, 1 máy 1 tiến trình riêng (do Electron tự bật) — chỉ
    # cần lắng nghe trên chính máy đó, không cần expose ra mạng ngoài, và
    # không cần reloader (không có ai sửa code khi app đã đóng gói chạy thật).
    port = int(os.environ.get("PORT", 5678))
    app.run(host="127.0.0.1", port=port, debug=False, use_reloader=False)