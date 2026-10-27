# Tóm tắt dự án Football Analytics (Tymex) - để chuyển ngữ cảnh

> File này KHÔNG chứa khóa/mật khẩu. Không dán khóa vào đây.

## 1. Mục tiêu
Web phân tích bóng đá cá nhân (lịch thi đấu, bảng xếp hạng, dự đoán Poisson, lịch sử dự đoán). Chỉ một mình Tuyen dùng, xem trên điện thoại ở mọi mạng, chỉ cần đăng nhập (tên đăng nhập + mật khẩu).

## 2. Kiến trúc
Nguồn dữ liệu (football-data.org) -> GitHub Actions (mỗi 3 giờ + chạy tay) chạy `scripts/cloud_sync.py` -> đồng bộ + tính dự đoán -> đẩy lên Supabase (bảng `matches`, `analysis`, `kv`, RLS chỉ cho `authenticated` đọc; file SQLite lưu ở Storage bucket `tymex-private`) -> web tĩnh trong `web/` (Cloudflare Worker static assets) đọc bằng supabase-js sau khi đăng nhập.

- Frontend: Cloudflare Worker, URL https://tymex.tuyenjp23.workers.dev, cấu hình `wrangler.jsonc` (assets = `./web`), tự deploy khi push lên `main`.
- Đăng nhập: Supabase Auth, tên đăng nhập `tuyen` được ánh xạ thành email `tuyen@tymex.app` (tắt đăng ký, user tạo sẵn).
- Mã nguồn: GitHub repo private `Tymex` (đẩy bằng GitHub Desktop). Repo public cũ `Tymex-football` cần xóa.

## 3. File quan trọng
- `app/cloud/supabase.py`, `app/cloud/export.py`, `scripts/cloud_sync.py`: phần đẩy dữ liệu lên Supabase.
- `cloud/supabase_schema.sql`: tạo bảng (chạy trong Supabase SQL Editor).
- `.github/workflows/sync.yml` (bản gốc `cloud/github-workflow-sync.yml`): workflow đồng bộ.
- `web/index.html`, `web/app.js`, `web/data.js`, `web/styles.css`, `web/config.js`: giao diện.
- `HUONG_DAN_CLOUD.md`: hướng dẫn triển khai.
- `app/prediction/poisson.py`: mô hình (chưa đổi).

## 4. Cấu hình (giá trị thật KHÔNG ghi ở đây)
`web/config.js` (khóa anon là public, được phép nằm trong file này):
```js
window.TYMEX_CONFIG = {
  SUPABASE_URL: "https://<project-id>.supabase.co",
  SUPABASE_ANON_KEY: "<anon key, MỘT dòng>",
  USERNAME_DOMAIN: "tymex.app",
};
```
GitHub Secrets (Settings > Secrets and variables > Actions): `FOOTBALL_DATA_API_KEY`, `SUPABASE_URL`, `SUPABASE_SERVICE_KEY` (khóa `sb_secret_...` hoặc `service_role`).

Quy tắc bắt buộc:
- `SUPABASE_URL` chỉ là `https://<project-id>.supabase.co`, KHÔNG có `/rest/v1/`.
- Mọi khóa/secret phải nằm trên một dòng, KHÔNG bấm Enter sau khi dán (ký tự xuống dòng gây lỗi cú pháp ở `config.js` và `InvalidURL` ở workflow).
- Khóa `service_role`/`sb_secret_` chỉ để trong GitHub Secrets, không đưa vào `config.js`, không commit `.env`, repo luôn private.

## 5. Đã xong
- Review, vá bảo mật, sửa N+1, `start.bat`; 83 test chạy qua.
- Triển khai Cloudflare + Supabase + GitHub; trang đăng nhập hoạt động, đăng nhập được.

## 6. Còn dang dở (làm tiếp từ đây)
1. Workflow "Đồng bộ dữ liệu" lần #1 bị lỗi: `httpx.InvalidURL ... '\n' at position 49` tại `client.ensure_bucket(BUCKET)`. Nguyên nhân: secret `SUPABASE_URL` trên GitHub dính đuôi `/rest/v1/` và ký tự xuống dòng. Cần cập nhật lại 3 secret (một dòng, đúng URL), rồi Actions > Đồng bộ dữ liệu > Run workflow. Trang web hiện báo "Chưa có dữ liệu" cho đến khi lần chạy này xanh.
2. Sửa code để tự `strip()` khoảng trắng/xuống dòng và bỏ `/rest/v1/` ở `SUPABASE_URL`/`SUPABASE_SERVICE_KEY` (chưa làm, Tuyen chưa đồng ý).
3. Xóa repo public `Tymex-football`.
4. Kiểm tra bảng đã tạo trong Supabase (đã chạy `cloud/supabase_schema.sql` chưa) khi workflow chạy lại.

## 7. Kế hoạch về sau: thêm nguồn dữ liệu
- Nguồn API khác: thêm lớp kế thừa `FootballDataProvider` trong `app/data_providers/`, thêm secret mới nếu cần, sửa workflow, push.
- Nguồn CSV: viết `scripts/import_csv.py` (cần file CSV mẫu để ánh xạ cột), đặt file vào `data_import/`, workflow tự nhập. Cần bảng quy đổi tên đội, ghi kèm tên nguồn, nhập lặp không tạo trùng.
- Không khuyến nghị cào (scraping) web; ưu tiên API chính thức hoặc file công khai. Kiểm tra điều khoản sử dụng của từng nguồn.
- Hoãn: hiệu chỉnh Dixon-Coles cho mô hình Poisson cho đến khi có dữ liệu thật để backtest.
- (2026-10-26) Đã triển khai hiệu chỉnh Dixon-Coles (ρ = −0,08, `MODEL_VERSION = "poisson-v2-dc"`, `score_matrix(..., rho=...)`, `predict()` dùng sẵn) vì kho dữ liệu thật đã đủ lớn (~21 nghìn trận nhập lịch sử) để việc hiệu chỉnh có ý nghĩa. Cùng đợt: thêm `app/prediction/live.py` (dự đoán trực tiếp `predict_live` + mô phỏng `simulate_match`), endpoint `GET /api/matches/{id}/live-prediction`, và trang **Trực tiếp** ở bản web lấy tỷ số/thống kê trực tiếp phía trình duyệt từ ESPN (nhiều giải châu Âu/Á/Mỹ, Cúp C1 ưu tiên) + quét toàn cầu TheSportsDB (phủ K League, V.League), kèm chế độ mô phỏng có gắn nhãn rõ. Dự đoán trước trận vẫn chỉ chạy trên các giải đã đồng bộ football-data.org/Supabase như cũ.
- (2026-10-26) Thêm khối "Nhận định dự đoán" 3 thị trường cho mỗi trận: `app/prediction/markets.py` (Tài/Xỉu bàn thắng đủ mốc 0,5–4,5 + BTTS + cơ hội kép + `verdict` có cấu trúc; `predict()` trả thêm khóa `markets`/`verdict`) và `app/prediction/corners.py` (mô hình Tài/Xỉu phạt góc 7,5–12,5, tỷ lệ góc được/bị co về TB giải). Góc lấy từ ESPN (`wonCorners`) vì football-data.org không có: bản web tự tính phía trình duyệt từ ~20 trận gần nhất của giải, `scripts/fetch_corners_espn.py` thu thập sẵn ra `data/corners/<slug>.json` nhưng CHƯA nối vào cloud_sync/Supabase. Ngưỡng nêu lựa chọn chung toàn hệ thống: Mạnh ≥ 65%, Khá ≥ 57%, sàn tuyệt đối 50%.
- (2026-10-26) Trang Trực tiếp: sửa nút quay lại theo route trước đó (không dùng `history.back()`), thêm chip sắp đá 1/3/6/12 giờ + “Hôm nay”, đếm ngược, xem lịch theo ngày, dấu thời gian cập nhật nhận định và yếu tố đội hình xuất phát (`lineups.py`, ±4%/trụ cột, chặn ±15%); kiểm soát bóng được `scripts/sample_live.py` ghi trung tâm vào Supabase `kv` theo workflow lặp 52 phút mỗi giờ, chu kỳ 90 giây (~1–2 phút/mẫu, có thể khuyết quanh chuyển ca). Đồng thời chống trùng cặp đấu ở 3 lớp: gộp ESPN/TheSportsDB trong `live.js`, dedupe phòng thủ trong `data.js`, và gộp trước upsert trong `cloud/export.py` (không gộp đảo chiều sân hay khác ngày).
- (2026-10-26) Thêm mục **Dự đoán vô địch** (trang "Vô địch" `#/outrights` ở bản web + bản máy tính, endpoint `GET /api/outrights`, module `app/prediction/outrights.py`). Hai nguồn đặt cạnh nhau: (1) kèo outright từ **The Odds API** (trung vị tỉ lệ giữa các nhà cái, chuẩn hóa loại lãi nhà cái; phát hiện môn qua `/sports?outrights=true` miễn phí, ánh xạ theo tiêu đề cho PL/PD/BL1/SA/FL1 + Champions League); (2) **mô phỏng Monte Carlo** phần còn lại của mùa giải bằng chính ma trận Poisson/Dixon-Coles (mặc định 3.000 lần, 2.000 nếu còn >300 trận; giải cúp như C1 không mô phỏng). Gating hạn mức: chỉ lấy kèo mới khi dữ liệu cũ >36 giờ, tối đa 10 lần gọi/lần chạy, dừng khi credit còn <60. Payload ở Supabase `kv` khóa `outrights`, dựng trong `cloud_sync.py` với cách ly lỗi hoàn toàn (publish nhận thêm tham số `outrights=`). Lưu ý: chủ dự án từng đề xuất lấy kèo từ 8xbet — không khả thi (không có API công khai, kèo sau đăng nhập trong app chống bot, tên miền xoay vòng qua các trang SEO) nên dùng The Odds API và ghi nhãn nguồn trung thực, không gán nhãn 8xbet.
- (2026-10-26) Bản web thành **PWA cài đặt được**: `web/manifest.json` (tên “Tymex — Phân tích & dự đoán bóng đá”, standalone, màu `#0e1626`), biểu tượng ở `web/icons/` (SVG tự vẽ: bóng vàng `#f4b942` trên nền navy; PNG 192/512 + maskable-512 render bằng cairosvg), và `web/sw.js` đệm vỏ ứng dụng (điều hướng network-first, tài nguyên cùng nguồn stale-while-revalidate, KHÔNG can thiệp request khác nguồn Supabase/ESPN/TheSportsDB). Nút “📲 Cài đặt ứng dụng” nằm ở trang Cài đặt (dùng `beforeinstallprompt`, ẩn khi đã chạy standalone). QUY TẮC PHÁT HÀNH: `VERSION` trong `sw.js` phải khớp hậu tố `?v=` trong `index.html` (đợt này: `20261026f`). Các PNG là file nhị phân — chưa lên GitHub qua kênh đẩy text, đang nằm trong cây làm việc chờ thêm bằng GitHub Desktop; bản SVG độc lập vẫn đủ điều kiện cài đặt.
- (2026-10-28) **Tỷ lệ thị trường có TRƯỚC giờ bóng lăn**: trước đây khối “Thị trường cược” ở trang phân tích thực tế chỉ hiện sau khi trận kết thúc, vì kèo trước trận chỉ lấy cho trận đá trong **30 giờ** tới (trần The Odds API **3 lần gọi/lần chạy** cho 5 giải, cổng làm mới gần 120 phút) trong khi trận đã đá luôn có sẵn kèo đóng cửa từ nhập lịch sử (cột AvgC/B365C của football-data.co.uk). Nay nới pipeline kèo (`app/odds/runner.py` + mặc định trong `scripts/cloud_sync.py`): cửa sổ **72 giờ**, trần **5 lần gọi/lần chạy**, cổng gần **180 phút** / cổng xa **1440 phút** — vẫn an toàn dưới gói 500 credit/tháng vì The Odds API tính credit theo lần gọi mỗi giải (không theo trận), cộng ngưỡng dừng `ODDS_MIN_REMAINING=40`; phần vắng mặt dùng chung `ODDS_HOURS_AHEAD` nên cũng nhìn trước 72 giờ. Kèm theo: thông báo “chưa có kèo” nói rõ kèo tự cập nhật trong vòng 72 giờ trước giờ đá; hàng dự đoán ở trang Lịch sử dự đoán (kv `predictions:live`) được `publish()` gắn thêm khối `market` gọn (tỉ lệ + xác suất chuẩn hóa) khi trận đã có kèo, và bản web hiện dòng “Thị trường: …” ngay dưới tên trận. Tăng `?v=`/`VERSION` service worker lên `20261026g`.

## 8. Ghi chú khi làm việc với Tuyen
- Trả lời tiếng Việt, hướng dẫn từng bước đơn giản (Tuyen không rành Git/CLI, dùng GitHub Desktop và giao diện web).
- Gọi công ty là "ナカシマ".
- Không tự ý ghi vào `library\Claude` khi chưa hỏi.
