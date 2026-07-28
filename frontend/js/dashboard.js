/* ==========================================================================
   RB CONTROL TRACKING - DASHBOARD SCRIPT
   Thẻ thống kê lấy số liệu thật từ API (tram-list, history, ipc-list, suvu-list).
   Bảng "Sự vụ mới nhất" bên dưới vẫn dùng dữ liệu giả (mock) để minh hoạ layout.
   ========================================================================== */

(function () {
    'use strict';

    /* ----------------------------------------------------------------------
       1. API (Flask backend — URL cấu hình trong js/config.js, load trước file này)
       ---------------------------------------------------------------------- */
    /* Backend đôi lúc phản hồi rất chậm (Shared Drive đồng bộ chậm, mạng yếu...)
       — không giới hạn thời gian thì request sẽ treo vô thời hạn mà không báo
       lỗi gì. Tự hủy sau 25s và báo rõ nguyên nhân thường gặp nhất. */
    function fetchWithTimeout(url, options, timeoutMs = 25000) {
        const controller = new AbortController();
        const timer = setTimeout(() => controller.abort(), timeoutMs);
        return fetch(url, { ...(options || {}), signal: controller.signal })
            .catch(err => {
                if (err.name === 'AbortError') {
                    const friendly = new Error('Máy chủ phản hồi quá lâu (có thể do Shared Drive đồng bộ chậm hoặc mạng yếu). Kiểm tra rồi thử lại.');
                    friendly.name = 'AbortError';
                    throw friendly;
                }
                throw err;
            })
            .finally(() => clearTimeout(timer));
    }
    async function apiGet(path) {
        const res  = await fetchWithTimeout(`${API_BASE}/${path}`);
        const data = await res.json().catch(() => null);
        if (!res.ok || !data || data.ok === false) throw new Error((data && data.error) || 'Lỗi máy chủ');
        return data;
    }

    // Ánh xạ trangThai (suvu-list.php, quy trình 6 bước) -> nhãn hiển thị + class CSS
    const STATUS_MAP = {
        'chua-xu-ly':        { text: 'Chưa xử lý',                              className: 'badge-new' },
        'dang-kiem-tra':     { text: 'KTV đang kiểm tra',                       className: 'badge-progress' },
        'da-tim-loi':        { text: 'Đã tìm ra lỗi',                           className: 'badge-progress' },
        'gui-linh-kien':     { text: 'Linh kiện đang gửi ra site',              className: 'badge-progress' },
        'linh-kien-den-noi': { text: 'Linh kiện đến nơi, đang khắc phục',       className: 'badge-pending' },
        'da-fix-dong-case':  { text: 'Đã fix, đóng case',                       className: 'badge-done' }
    };
    const MUCDO_LABEL = { 'khan-cap': '🔴 Khẩn cấp', 'qua-han': '🟠 Quá hạn (nhắc lại)', 'moi-xuat-hien': '🔵 Mới xuất hiện' };

    /* ----------------------------------------------------------------------
       2. ĐỒNG HỒ NGÀY GIỜ THỜI GIAN THỰC
       ---------------------------------------------------------------------- */
    const WEEKDAYS = ['Chủ Nhật', 'Thứ Hai', 'Thứ Ba', 'Thứ Tư', 'Thứ Năm', 'Thứ Sáu', 'Thứ Bảy'];

    function pad(n) { return n < 10 ? '0' + n : '' + n; }

    function updateClock() {
        const now = new Date();
        const timeStr = pad(now.getHours()) + ':' + pad(now.getMinutes()) + ':' + pad(now.getSeconds());
        const dateStr = WEEKDAYS[now.getDay()] + ', ' + pad(now.getDate()) + '/' + pad(now.getMonth() + 1) + '/' + now.getFullYear();

        const timeEl = document.getElementById('clockTime');
        const dateEl = document.getElementById('clockDate');
        if (timeEl) timeEl.textContent = timeStr;
        if (dateEl) dateEl.textContent = dateStr;
    }

    /* ----------------------------------------------------------------------
       3. THẺ THỐNG KÊ - lấy số liệu thật từ danh sách trạm / trụ / IPC / sự vụ
       ---------------------------------------------------------------------- */
    // Đếm số dòng của một danh sách; trả về null nếu không lấy được (chưa có backend/lỗi mạng)
    async function fetchCount(path) {
        try {
            const data = await apiGet(path);
            return (data.items || []).length;
        } catch (err) {
            console.error(err);
            return null;
        }
    }

    async function loadStats() {
        const [tramCount, truCount, ipcCount, suvuItems] = await Promise.all([
            fetchCount('tram-list.php'),
            fetchCount('history.php'),
            fetchCount('ipc-list.php'),
            apiGet('suvu-list.php').then(function (d) { return d.items || []; }).catch(function (err) { console.error(err); return null; })
        ]);

        const suvuOpenCount = Array.isArray(suvuItems)
            ? suvuItems.filter(function (r) { return (r.trangThai || 'chua-xu-ly') !== 'da-fix-dong-case'; }).length
            : null;

        return [
            { label: 'Tổng Trạm',      value: tramCount,     icon: '📡', color: 'blue',   link: 'on-tram.html?tab=list' },
            { label: 'Tổng Trụ',       value: truCount,      icon: '🔌', color: 'cyan',   link: 'test-tru.html?tab=list' },
            { label: 'Tổng IPC',       value: ipcCount,      icon: '💻', color: 'indigo', link: 'test-ipc.html' },
            { label: 'Sự Vụ đang mở',  value: suvuOpenCount, icon: '⚠️', color: 'amber',  link: 'su-vu.html?tab=list' }
        ];
    }

    function renderStats(stats) {
        const container = document.getElementById('statsGrid');
        if (!container) return;

        container.innerHTML = stats.map(function (item, index) {
            return (
                '<a class="stat-card" href="' + item.link + '" style="animation-delay:' + (index * 0.08) + 's">' +
                    '<div class="stat-info">' +
                        '<div class="stat-value">' + (item.value === null ? '—' : item.value) + '</div>' +
                        '<div class="stat-label">' + item.label + '</div>' +
                    '</div>' +
                    '<div class="stat-icon-box ' + item.color + '"><i>' + item.icon + '</i></div>' +
                '</a>'
            );
        }).join('');
    }

    /* ----------------------------------------------------------------------
       4. RENDER BẢNG SỰ VỤ MỚI NHẤT (lấy từ api/suvu-list.php, tối đa 5 dòng)
          Sự vụ khẩn cấp chưa đóng case luôn được đẩy lên đầu bảng và tô đỏ.
       ---------------------------------------------------------------------- */
    function isUrgentOpen(r) {
        return r.mucDo === 'khan-cap' && (r.trangThai || 'chua-xu-ly') !== 'da-fix-dong-case';
    }

    async function renderIncidents() {
        const tbody = document.getElementById('incidentsBody');
        if (!tbody) return;

        let items = [];
        try { items = (await apiGet('suvu-list.php')).items || []; }
        catch (err) { console.error(err); }

        // Đã fix, đóng case thì không cần hiện ở dashboard nữa
        items = items.filter(function (r) { return (r.trangThai || 'chua-xu-ly') !== 'da-fix-dong-case'; });

        if (!items.length) {
            tbody.innerHTML = '<tr><td colspan="5" style="text-align:center;color:#9ca3af;padding:30px 22px;">Không có sự vụ nào đang mở.</td></tr>';
            return;
        }

        const sorted = items.slice().sort(function (a, b) {
            const au = isUrgentOpen(a) ? 1 : 0, bu = isUrgentOpen(b) ? 1 : 0;
            if (au !== bu) return bu - au; // khẩn cấp chưa xong lên đầu
            return (b.id || 0) - (a.id || 0);
        });
        const latest = sorted.slice(0, 5);

        tbody.innerHTML = latest.map(function (item) {
            const status = STATUS_MAP[item.trangThai || 'chua-xu-ly'] || { text: item.trangThai, className: '' };
            const urgent = isUrgentOpen(item);
            return (
                '<tr' + (urgent ? ' class="row-urgent"' : '') + ' style="cursor:pointer" onclick="location.href=\'su-vu.html?tab=list&openId=' + item.id + '\'">' +
                    '<td class="cell-code">' + item.maTram + '</td>' +
                    '<td class="cell-code">' + item.maTru + '</td>' +
                    '<td class="cell-error"><i>' + (urgent ? '🚨' : '❗') + '</i>' + item.moTa + '</td>' +
                    '<td><span class="badge ' + status.className + '">' + status.text + '</span></td>' +
                    '<td class="cell-time">' + item.time + '</td>' +
                '</tr>'
            );
        }).join('');
    }

    /* ----------------------------------------------------------------------
       5. THÔNG TIN NGƯỜI DÙNG (lấy từ localStorage nếu đã đăng nhập)
       ---------------------------------------------------------------------- */
    function renderUserInfo() {
        const nameEl = document.getElementById('userName');
        const roleEl = document.getElementById('userRole');
        const avatarEl = document.getElementById('userAvatar');

        // Dữ liệu mặc định khi chưa có backend / chưa đăng nhập
        let username = 'admin';
        let role = 'viewer';

        try {
            const stored = localStorage.getItem('user');
            if (stored) {
                const user = JSON.parse(stored);
                username = user.username || username;
                role = user.role || role;
            }
        } catch (e) {
            // Bỏ qua nếu dữ liệu localStorage không hợp lệ
        }

        if (nameEl) nameEl.textContent = username;
        if (roleEl) roleEl.textContent = role;
        if (avatarEl) avatarEl.textContent = username.trim().charAt(0).toUpperCase();

        // Mục "Cài Đặt" (duyệt tài khoản đăng ký) chỉ dành cho admin
        const navSettings = document.getElementById('navSettings');
        if (navSettings) navSettings.style.display = (role === 'admin') ? '' : 'none';
    }

    /* ----------------------------------------------------------------------
       6. SIDEBAR: TOGGLE TRÊN MOBILE
       ---------------------------------------------------------------------- */
    function setupSidebarToggle() {
        const sidebar = document.getElementById('sidebar');
        const overlay = document.getElementById('sidebarOverlay');
        const toggleBtn = document.getElementById('menuToggle');

        if (!sidebar || !overlay || !toggleBtn) return;

        function openSidebar() {
            sidebar.classList.add('open');
            overlay.classList.add('show');
        }
        function closeSidebar() {
            sidebar.classList.remove('open');
            overlay.classList.remove('show');
        }

        toggleBtn.addEventListener('click', function () {
            sidebar.classList.contains('open') ? closeSidebar() : openSidebar();
        });
        overlay.addEventListener('click', closeSidebar);
    }

    /* ----------------------------------------------------------------------
       7. ĐĂNG XUẤT
       ---------------------------------------------------------------------- */
    function setupLogout() {
        const logoutBtn = document.getElementById('logoutBtn');
        if (!logoutBtn) return;

        logoutBtn.addEventListener('click', function (e) {
            e.preventDefault();
            const confirmed = window.confirm('Bạn có chắc chắn muốn đăng xuất?');
            if (!confirmed) return;

            localStorage.removeItem('user');
            localStorage.removeItem('token');
            window.location.href = 'login.html';
        });
    }

    /* ----------------------------------------------------------------------
       8. KHỞI CHẠY
       ---------------------------------------------------------------------- */
    document.addEventListener('DOMContentLoaded', function () {
        renderUserInfo();
        loadStats().then(renderStats);
        renderIncidents();
        setupSidebarToggle();
        setupLogout();

        updateClock();
        setInterval(updateClock, 1000);
    });
})();
