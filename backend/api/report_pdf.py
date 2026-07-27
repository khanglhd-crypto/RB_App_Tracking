"""
Xuất Phiếu Ảnh (Test Trụ) thành PDF, và phục vụ lại file đã xuất.

Nhận HTML đã dựng sẵn ở frontend (ảnh đã nhúng dạng base64, tự chứa toàn bộ
nội dung), render bằng Chromium headless (Playwright) rồi lưu file PDF ngay
trên máy chủ, vào đúng thư mục trụ đã dùng khi lưu ảnh test trụ:
    <root_path>/Charge Point/<folderName>/Phieu_Test_<pillar>.pdf
Đường dẫn được ghi vào pillar_tests.pdf_path để mở lại xem sau này qua
GET /api/pillar-pdf.php?id=...
"""

import base64
import json
import os
import re
import subprocess
import sys
import tempfile

import psycopg2
from flask import Blueprint, jsonify, request, send_file

from audit import log_action
from database.db import get_connection

report_pdf_bp = Blueprint("report_pdf", __name__, url_prefix="/api")

CONFIG_PATH = os.path.join(os.path.dirname(os.path.dirname(__file__)), "server_config.json")
WORKER_PATH = os.path.join(os.path.dirname(os.path.dirname(__file__)), "pdf_worker.py")
DEFAULT_BASE_FOLDER = "Charge Point"

# Cột hợp lệ để ghi/đọc đường dẫn PDF trên pillar_tests — whitelist tránh SQL injection
# qua tên cột. "pdf_path" = PDF Test Xuất Xưởng, "nghiem_thu_pdf_path" = PDF Nghiệm Thu On Trạm,
# "nang_cap_pdf_path" = PDF Nâng Cấp Trụ Sạc.
PDF_LINK_COLUMNS = {"pdf_path", "nghiem_thu_pdf_path", "nang_cap_pdf_path"}

# baseFolder -> tên module ghi vào audit_log. "List Xu Ly Su Co" (Sự Vụ) không
# nằm trong danh sách này vì đã được ghi log riêng, rõ ràng hơn ở suvu.py
# (suvu-set-pdf.php), lúc gắn PDF vào đúng sự vụ.
MODULE_BY_BASE_FOLDER = {
    "Charge Point": "test_tru",
    "List On Tram": "on_tram",
    "Modify Charge Point": "nang_cap",
}


def _get_root_path():
    # Biến môi trường ROOT_PATH (đặt trên server thật, vd Render) được ưu tiên
    # hơn server_config.json — vì đường dẫn Windows cục bộ trong file đó không
    # tồn tại trên server Linux.
    env_path = os.environ.get("ROOT_PATH")
    if env_path:
        return env_path
    with open(CONFIG_PATH, "r", encoding="utf-8") as f:
        return json.load(f)["root_path"]


def _safe_name(name):
    return re.sub(r'[<>:"/\\|?*]', "_", name).strip() or "unnamed"


def _save_data_url_image(target_dir, label, data_url):
    """Giải mã 1 ảnh base64 (data URL) và ghi ra file .jpg trong target_dir."""
    header, b64data = data_url.split(",", 1)
    raw = base64.b64decode(b64data)
    path = os.path.join(target_dir, f"{_safe_name(label)}.jpg")
    with open(path, "wb") as f:
        f.write(raw)
    return path


@report_pdf_bp.route("/export-report-pdf.php", methods=["POST"])
def export_report_pdf():
    data = request.get_json(silent=True) or {}
    html = data.get("html") or ""
    pillar = (data.get("pillar") or "").strip()
    folder_name = (data.get("folderName") or "").strip() or _safe_name(pillar or "unnamed")
    # folderPath: mảng các cấp thư mục con (vd ["V.E.HCM1348","HCM1348.001","HCM1348.001"])
    # để lưu sâu nhiều cấp — nếu không có thì dùng folderName như 1 cấp duy nhất (cũ)
    folder_path = data.get("folderPath") or [folder_name]
    report_name = (data.get("reportName") or "Phieu_Test").strip()
    base_folder = (data.get("baseFolder") or DEFAULT_BASE_FOLDER).strip() or DEFAULT_BASE_FOLDER
    images = data.get("images") or []  # [{label, dataUrl}, ...] - ảnh lẻ lưu chung thư mục với PDF
    record_id = data.get("id")
    link_column = data.get("linkColumn") or "pdf_path"
    if link_column not in PDF_LINK_COLUMNS:
        link_column = "pdf_path"

    if not html:
        return jsonify({"ok": False, "error": "Thiếu nội dung phiếu để xuất PDF"}), 400
    if not pillar:
        return jsonify({"ok": False, "error": "Thiếu mã trụ sạc"}), 400

    try:
        root_path = _get_root_path()
    except (OSError, KeyError, json.JSONDecodeError) as err:
        return jsonify({"ok": False, "error": f"Không đọc được server_config.json: {err}"}), 500

    # "Charge Point" (Test Trụ Xuất Xưởng) nằm BÊN TRONG root_path (List End Of Line Test),
    # còn các baseFolder khác (vd "List On Tram") nằm NGANG HÀNG với root_path, không lồng vào nhau.
    base_dir = root_path if base_folder == DEFAULT_BASE_FOLDER else os.path.dirname(root_path)
    safe_segments = [_safe_name(seg) for seg in folder_path if str(seg or "").strip()]
    target_dir = os.path.join(base_dir, base_folder, *safe_segments) if safe_segments else os.path.join(base_dir, base_folder)
    try:
        os.makedirs(target_dir, exist_ok=True)
    except OSError as err:
        return jsonify({"ok": False, "error": f"Không tạo được thư mục lưu: {err}"}), 500

    try:
        for img in images:
            label = (img.get("label") or "").strip()
            data_url = img.get("dataUrl")
            if label and data_url:
                _save_data_url_image(target_dir, label, data_url)
    except (OSError, ValueError, IndexError) as err:
        return jsonify({"ok": False, "error": f"Không lưu được ảnh lẻ: {err}"}), 500

    pdf_path = os.path.join(target_dir, f"{_safe_name(report_name)}_{_safe_name(pillar)}.pdf")

    # Render bằng 1 tiến trình con riêng (pdf_worker.py) thay vì gọi Playwright
    # ngay trong tiến trình Flask — tránh bị ảnh hưởng khi Flask tự reload.
    tmp_html_path = None
    try:
        with tempfile.NamedTemporaryFile(mode="w", suffix=".html", delete=False, encoding="utf-8") as tmp:
            tmp.write(html)
            tmp_html_path = tmp.name

        result = subprocess.run(
            [sys.executable, WORKER_PATH, tmp_html_path, pdf_path],
            capture_output=True, text=True, timeout=60,
        )
        if result.returncode != 0:
            return jsonify({"ok": False, "error": f"Không xuất được PDF: {result.stderr.strip()}"}), 500
    except subprocess.TimeoutExpired:
        return jsonify({"ok": False, "error": "Xuất PDF quá thời gian chờ (60s)"}), 500
    finally:
        if tmp_html_path:
            try:
                os.remove(tmp_html_path)
            except OSError:
                pass

    module = MODULE_BY_BASE_FOLDER.get(base_folder)
    if module:
        log_action(module, "export", target=pillar, detail=report_name)

    if record_id:
        try:
            connection = get_connection()
            try:
                with connection.cursor() as cursor:
                    # link_column da duoc kiem tra nam trong PDF_LINK_COLUMNS (whitelist) o tren
                    cursor.execute(
                        f"UPDATE pillar_tests SET {link_column} = %s WHERE id = %s",
                        (pdf_path, record_id),
                    )
            finally:
                connection.close()
        except psycopg2.Error as err:
            # PDF đã xuất thành công, chỉ không lưu được liên kết để mở lại sau này
            return jsonify({
                "ok": True,
                "path": pdf_path,
                "warning": f"PDF đã lưu nhưng không ghi được liên kết xem lại: {err}",
            })

    return jsonify({"ok": True, "path": pdf_path})


@report_pdf_bp.route("/pillar-pdf.php", methods=["GET"])
def view_pillar_pdf():
    record_id = request.args.get("id")
    if not record_id:
        return jsonify({"ok": False, "error": "Thiếu id"}), 400

    pdf_type = request.args.get("type")
    if pdf_type == "nghiem-thu":
        link_column = "nghiem_thu_pdf_path"
    elif pdf_type == "nang-cap":
        link_column = "nang_cap_pdf_path"
    else:
        link_column = "pdf_path"

    try:
        connection = get_connection()
        try:
            with connection.cursor() as cursor:
                # link_column chi co 2 gia tri co dinh o tren, khong lay truc tiep tu request
                cursor.execute(f"SELECT {link_column} AS pdf_path FROM pillar_tests WHERE id = %s", (record_id,))
                row = cursor.fetchone()
        finally:
            connection.close()
    except psycopg2.Error as err:
        return jsonify({"ok": False, "error": f"Lỗi kết nối cơ sở dữ liệu: {err}"}), 500

    if not row or not row["pdf_path"]:
        return jsonify({"ok": False, "error": "Trụ này chưa xuất Phiếu Ảnh"}), 404
    if not os.path.isfile(row["pdf_path"]):
        return jsonify({"ok": False, "error": "Không tìm thấy file PDF trên máy chủ (có thể đã bị xóa/di chuyển)"}), 404

    return send_file(row["pdf_path"], mimetype="application/pdf")
