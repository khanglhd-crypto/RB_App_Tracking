import os

from flask import Flask, jsonify, send_from_directory
from flask_cors import CORS

from api.auth import auth_bp
from api.pillar_tests import pillar_tests_bp
from api.ipc import ipc_bp
from api.tram import tram_bp
from api.suvu import suvu_bp
from api.report_pdf import report_pdf_bp
from api.audit import audit_bp

# Thư mục frontend (HTML/CSS/JS tĩnh) — phục vụ luôn từ chính server Flask
# này để dùng nội bộ trong mạng công ty (LAN), không cần deploy 2 nơi riêng.
FRONTEND_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "frontend")

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
    # Chạy trực tiếp (python server.py) dùng cho dev cục bộ — trên Render,
    # gunicorn tự import biến `app` ở trên, không chạy qua nhánh này, và
    # Render tự cấp cổng qua biến môi trường PORT.
    port = int(os.environ.get("PORT", 5678))
    app.run(host="0.0.0.0", port=port, debug=True)