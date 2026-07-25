"""
Worker độc lập: render 1 file HTML thành PDF bằng Playwright (Chromium).

Chạy như 1 tiến trình con RIÊNG BIỆT (subprocess.run), tách hẳn khỏi tiến
trình Flask đang phục vụ request — nhờ vậy khi Flask tự động reload do sửa
code, việc mở Chromium để xuất PDF không bị ảnh hưởng/rớt giữa chừng.

Cách dùng: python pdf_worker.py <html_file> <output_pdf_path>
"""

import sys

from playwright.sync_api import sync_playwright


def main():
    html_path, pdf_path = sys.argv[1], sys.argv[2]
    with open(html_path, "r", encoding="utf-8") as f:
        html = f.read()

    with sync_playwright() as p:
        browser = p.chromium.launch()
        try:
            page = browser.new_page()
            page.set_content(html, wait_until="load")
            page.pdf(path=pdf_path, format="A4", print_background=True)
        finally:
            browser.close()


if __name__ == "__main__":
    main()
