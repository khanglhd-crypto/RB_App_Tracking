// URL gốc của backend API — dùng chung cho toàn bộ frontend.
// Chạy trên localhost (dev) thì tự trỏ về backend cục bộ; deploy thật
// (Vercel/GitHub Pages...) thì trỏ về URL backend đã deploy trên Render.
// CHỈ CẦN SỬA DÒNG "https://..." BÊN DƯỚI KHI ĐỔI CHỖ DEPLOY BACKEND.
const API_BASE = (location.hostname === 'localhost' || location.hostname === '127.0.0.1')
    ? 'http://127.0.0.1:5678/api'
    : 'https://YOUR-BACKEND-NAME.onrender.com/api';
