import os

from flask import Flask, jsonify
from flask_cors import CORS

from api.auth import auth_bp
from api.pillar_tests import pillar_tests_bp
from api.ipc import ipc_bp
from api.tram import tram_bp
from api.suvu import suvu_bp
from api.report_pdf import report_pdf_bp
from api.audit import audit_bp

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


if __name__ == "__main__":
    # Chạy trực tiếp (python server.py) dùng cho dev cục bộ — trên Render,
    # gunicorn tự import biến `app` ở trên, không chạy qua nhánh này, và
    # Render tự cấp cổng qua biến môi trường PORT.
    port = int(os.environ.get("PORT", 5678))
    app.run(host="0.0.0.0", port=port, debug=True)