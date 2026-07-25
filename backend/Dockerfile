# Dùng khi deploy trên Render (chọn Environment = Docker) — chỉ CẦN nếu cách
# build thường (Build Command: playwright install --with-deps chromium) báo
# lỗi thiếu quyền cài thư viện hệ thống cho Chromium.
# Image gốc của Microsoft đã có sẵn Chromium + toàn bộ thư viện cần thiết.
# LƯU Ý: số hiệu bản (v1.61.0) phải khớp với dòng playwright==... trong
# requirements.txt — nếu Docker Hub báo không tìm thấy tag này, vào
# https://mcr.microsoft.com/en-us/artifact/mar/playwright/python/tags
# để lấy đúng tag gần nhất rồi sửa dòng FROM bên dưới.
FROM mcr.microsoft.com/playwright/python:v1.61.0-jammy

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

CMD gunicorn server:app --bind 0.0.0.0:$PORT
