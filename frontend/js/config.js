// URL gốc của backend API — dùng chung cho toàn bộ frontend.
// Frontend giờ được phục vụ TỪ CHÍNH server Flask (xem server.py) — cùng
// gốc (origin) với API, nên chỉ cần đường dẫn tương đối "/api" là tự đúng
// ở MỌI nơi: máy bạn (127.0.0.1:5678), LAN công ty (192.168.x.x:5678),
// hay sau khi deploy thật trên Render (https://...onrender.com).
// Chỉ có 1 ngoại lệ: mở file trực tiếp bằng file:// (không qua server nào)
// thì phải gọi thẳng vào địa chỉ đầy đủ 127.0.0.1:5678 để test cục bộ.
const API_BASE = (location.protocol === 'file:')
    ? 'http://127.0.0.1:5678/api'
    : '/api';
