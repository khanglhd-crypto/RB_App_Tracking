import os
import sys

# Khi đóng gói bằng PyInstaller, trình duyệt Chromium của Playwright được kèm
# theo vào _internal/ms-playwright thay vì %LOCALAPPDATA%\ms-playwright mặc
# định — phải trỏ PLAYWRIGHT_BROWSERS_PATH tới đó TRƯỚC khi playwright được
# import ở bất kỳ đâu (api/report_pdf.py), nếu không sẽ báo "Executable
# doesn't exist".
if getattr(sys, "frozen", False) and hasattr(sys, "_MEIPASS"):
    bundled_browsers = os.path.join(sys._MEIPASS, "ms-playwright")
    if os.path.isdir(bundled_browsers):
        os.environ["PLAYWRIGHT_BROWSERS_PATH"] = bundled_browsers

from flask import Flask, jsonify, send_from_directory
from flask_cors import CORS

from api.auth import auth_bp
from api.pillar_tests import pillar_tests_bp
from api.ipc import ipc_bp
from api.tram import tram_bp
from api.suvu import suvu_bp
from api.report_pdf import report_pdf_bp
from api.audit import audit_bp


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


@app.route("/api/health")
def health():
    return jsonify({"status": "ok"})


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