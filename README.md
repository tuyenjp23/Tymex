# Football Analytics cá nhân

Website phân tích bóng đá chạy trên máy Windows của bạn: lịch thi đấu, phong độ, đối đầu, sân nhà/khách, dự đoán bằng mô hình Poisson, lịch sử dự đoán có chấm điểm. Giao diện tiếng Việt, dùng được trên điện thoại.

## 1. Cài đặt và chạy (3 bước)

1. Cài **Python 3.10 trở lên** từ https://www.python.org/downloads/ (nhớ tick **Add python.exe to PATH**).
2. Lấy **khóa API miễn phí** tại https://www.football-data.org/client/register (khóa gửi qua email).
3. Nhấp đúp **`start.bat`**. Lần đầu script tự tạo môi trường ảo và cài thư viện (1–2 phút), sau đó mở trình duyệt tại http://127.0.0.1:8000.

Trên website: vào **Cài đặt** → dán khóa → **Lưu khóa** → **Kiểm tra khóa** → **Cập nhật dữ liệu**.
Lần đồng bộ đầu mất khoảng 1–3 phút (gói miễn phí giới hạn 10 lần gọi/phút; ứng dụng tự chờ, bạn không cần làm gì). Hoặc tự sửa file `.env` (sao chép từ `.env.example`).

Tắt website: đóng cửa sổ đen của `start.bat`.

## 2. Dùng trên điện thoại (cùng Wi-Fi)

Mở cửa sổ lệnh trong thư mục dự án và chạy `.venv\Scripts\python run.py --host 0.0.0.0`, rồi mở `http://<IP-máy-tính>:8000` trên điện thoại (xem IP bằng lệnh `ipconfig`). Có thể phải cho phép Python qua Windows Firewall. Điện thoại chỉ xem được; việc đổi khóa API chỉ cho phép từ chính máy tính chạy ứng dụng. Không mở cổng này ra Internet khi chưa thêm đăng nhập.

## 3. Các trang

| Trang | Nội dung |
|---|---|
| Tổng quan | Đang đá, hôm nay, ngày mai, sắp diễn ra, đã kết thúc; lọc theo giải, tìm đội |
| Lịch thi đấu | Xem theo ngày (‹ ›), lọc giải/đội, hoặc toàn bộ lịch một đội |
| Chi tiết trận | Dự đoán, phong độ 5/10 trận, sân nhà/khách, đối đầu, kết luận, bài AI (tùy chọn) |
| Bảng xếp hạng | Theo giải |
| Đội bóng | Danh sách, bấm để xem lịch của đội |
| Lịch sử dự đoán | Dự đoán đã lưu trước trận + Brier, log loss, độ chính xác, sai số bàn thắng theo giải/tháng |
| Cài đặt | Khóa API, chọn giải, đồng bộ, nhật ký |

Múi giờ mặc định **Asia/Tokyo**, đổi ngay trên thanh trên cùng; mọi giờ đều ghi rõ múi giờ.

## 4. Nguồn dữ liệu và giới hạn (quan trọng)

Dùng **football-data.org** (v4). Theo tài liệu công khai của họ, gói miễn phí có khoảng 12 giải (Premier League, La Liga, Bundesliga, Serie A, Ligue 1, Champions League...), **10 lần gọi/phút**, điểm số có thể trễ, và **không** có xG, cú sút, kiểm soát bóng, chấn thương, treo giò, đội hình. Vì vậy:

- Các mục đó hiển thị **"nguồn dữ liệu hiện tại không cung cấp"**; hệ thống không bao giờ suy đoán chấn thương hay đội hình.
- Quyền truy cập mùa trước phụ thuộc gói của bạn. Nếu bị từ chối, ứng dụng vẫn chạy với mùa hiện tại; mô hình sẽ báo "chưa đủ dữ liệu" đầu mùa thay vì đưa con số giả.
- Gói có thể thay đổi; hãy kiểm tra trang giá của football-data.org.

Cache: dữ liệu lưu trong SQLite (`data/football.db`). Không gọi lại API cho một giải nếu vừa đồng bộ dưới 15 phút (trừ khi bấm "Ép cập nhật"). Tự đồng bộ nền mỗi 180 phút (đặt `AUTO_SYNC_MINUTES=0` để tắt).

## 5. Dự đoán hoạt động thế nào

Mô hình Poisson + Dixon-Coles (`app/prediction/poisson.py`, phiên bản `poisson-v2-dc`): từ các trận đã kết thúc của giải trong 400 ngày trước trận (trọng số giảm dần theo thời gian), tính tấn công/phòng ngự **riêng sân nhà và sân khách** của mỗi đội, co về mức trung bình giải để tránh mẫu nhỏ, suy ra bàn thắng kỳ vọng λ của hai đội, dựng ma trận tỷ số Poisson, **hiệu chỉnh Dixon-Coles** (ρ = −0,08) cho 4 ô tỷ số thấp 0-0, 1-0, 0-1, 1-1 — Poisson độc lập thuần vốn đánh giá thấp các trận hòa ít bàn và đánh giá cao thắng tối thiểu — rồi cộng thành xác suất thắng/hòa/thua (làm tròn sao cho tổng đúng 100%).

- Chỉ dùng trận **đã kết thúc trước giờ bóng lăn**; kết quả tương lai không bao giờ lọt vào.
- Thiếu dữ liệu (dưới 6 trận mỗi đội hoặc dưới 40 trận của giải) → hiện cảnh báo, **không tạo dự đoán**.
- Dự đoán được **lưu trước trận** (kèm thời điểm) khi bạn mở trang trận hoặc sau mỗi lần đồng bộ; không bao giờ ghi đè hay xóa. Khi có kết quả thật, hệ thống chấm điểm tự động. Trang Lịch sử dự đoán hiển thị cả dự đoán sai.
- "Kiểm tra lại trên trận cũ" (backtest) chạy mô hình trên các trận đã đá chỉ bằng dữ liệu trước trận đó, để đo chất lượng ngay khi chưa có nhiều dự đoán thật. Kết quả này tách riêng, không trộn với dự đoán thật.
- Mô hình **không biết** chấn thương, đội hình, động lực, thời tiết. Hãy coi đây là công cụ tham khảo, không phải lời khuyên cá cược.

## Bổ sung (2026-10-26): dự đoán trực tiếp, thống kê trực tiếp và mô phỏng

**Dự đoán trực tiếp trong trận (kiểu FotMob)** — `app/prediction/live.py` + endpoint `GET /api/matches/{id}/live-prediction` (bản máy tính) và trang **Trực tiếp** (bản web):

- Cách tính: lấy λ của dự đoán **trước trận đã lưu**, chỉ mô hình hóa phần thời gian còn lại (trận coi như 95 phút hiệu dụng gồm bù giờ), nhân hệ số trạng thái (đội đang thua tấn công mạnh hơn ×1,12/bàn, đội đang thắng giảm nhịp ×0,90/bàn, tối đa 2 bàn) và hệ số thẻ đỏ (đội bị thẻ ×0,72/thẻ, đối thủ ×1,10/thẻ), cộng phân phối bàn thắng còn lại (có hiệu chỉnh Dixon-Coles) vào tỷ số hiện tại. Kết quả: xác suất thắng/hòa/thua trực tiếp, các tỷ số **chung cuộc** khả thi nhất, tỷ số kỳ vọng chung cuộc, xác suất bàn thắng tiếp theo.
- Không có dự đoán trước trận đã lưu, trận không đang đá, hoặc chưa có tỷ số trực tiếp → trả `{"available": false, "reason": ...}`, **không bao giờ tự bịa λ**.
- football-data.org không cung cấp phút thi đấu và thẻ đỏ trực tiếp: phút trên bản máy tính là **ước tính từ giờ bóng lăn** (trừ ~15 phút nghỉ giữa hiệp, có ghi rõ trong phản hồi; truyền `?minute=` để dùng phút chính xác) và thẻ đỏ tính bằng 0.
- Bản web (trang Trực tiếp) lấy tỷ số/phút **thật, trực tiếp từ trình duyệt**: ESPN cho các giải lớn ở châu Âu (Champions League/Cúp C1, Europa League, Conference League, 5 giải VĐQG lớn, các cúp quốc gia...), châu Á (AFC Champions League Elite/Two, J.League, Saudi Pro League, Trung Quốc, Thái Lan, Indonesia, Malaysia, Ấn Độ, Úc...) và châu Mỹ (Libertadores, Sudamericana, MLS, Liga MX, Brazil, Argentina...) — nhóm ưu tiên làm mới mỗi 60 giây, các giải còn lại tối đa 4 phút/lần — cộng một lượt **quét toàn cầu của TheSportsDB** để phủ các giải ESPN không có (K League 1 của Hàn Quốc, V.League 1 của Việt Nam...) và dự phòng khi ESPN sập. Mỗi thẻ trận ghi rõ nguồn của trận đó.
- **Thống kê trực tiếp**: mở một trận ESPN sẽ tải thống kê chi tiết của chính trận đó (kiểm soát bóng, cú sút, sút trúng đích, phạt góc, việt vị, phạm lỗi, cứu thua, thẻ, chuyền bóng... — chỉ hiện những gì ESPN thật sự trả về cho trận đó), dòng sự kiện bàn thắng/thẻ/thay người, và biểu đồ **"Biến động xác suất thắng"** do mô hình trực tiếp tính lại tại các thời điểm ghi bàn đã biết (đây là đầu ra của mô hình, không phải dữ liệu thế trận thật). Số "xG ước tính từ cú sút" nếu có là ước tính thô của Tymex (sút trúng đích × 0,32 + sút còn lại × 0,03), luôn ghi rõ không phải xG chính thức.
- **Phạm vi dự đoán trước trận không đổi**: dự đoán Tymex vẫn chỉ có cho các giải đã đồng bộ qua football-data.org/Supabase (gói miễn phí giới hạn số giải). Các giải chỉ có ở lớp trực tiếp mà chưa có dự đoán Tymex sẽ dùng λ trung bình giải và **ghi rõ nhãn "ước tính theo trung bình giải"** trên từng trận.

**Chế độ mô phỏng trực tiếp** — nút **▶ Mô phỏng** trên trang Trực tiếp (và hàm `simulate_match` trong `app/prediction/live.py`):

- Mô phỏng từng phút một trận (từ đầu, hoặc tiếp từ trạng thái hiện tại của trận đang đá) bằng chính λ và mô hình trực tiếp ở trên: đồng hồ, tỷ số, thanh xác suất và biểu đồ biến động cập nhật theo tốc độ bạn chọn (0,25–1 giây/phút), kèm dòng sự kiện mô phỏng (bàn thắng, cơ hội nguy hiểm).
- Đây là diễn biến **GIẢ LẬP bằng mô hình, không phải trận thật** — banner "MÔ PHỎNG" luôn hiện trên đầu panel. Đừng dùng kết quả mô phỏng làm nhận định về trận thật.

**Giới hạn trung thực**: mô hình trực tiếp không có dữ liệu cú sút/xG/thế trận theo phút nên chỉ phản ứng theo tỷ số, thời gian và thẻ đỏ; xác suất là ước lượng thống kê, không phải cam kết kết quả. Coi mọi con số là công cụ tham khảo, không phải lời khuyên cá cược.

## 6. AI viết bài (tùy chọn)

Để trống thì mọi thứ vẫn chạy. Nếu thêm `ANTHROPIC_API_KEY` vào `.env`, trang trận sẽ có nút **Viết bài bằng AI**: hệ thống gửi cho AI một bản JSON số liệu đã tính, yêu cầu viết bài tiếng Việt và cấm thêm thông tin ngoài bản đó. Bài được lưu kèm thời điểm và mã dữ liệu; khi dữ liệu đổi sẽ báo "bài đã cũ" để tạo lại. Chỉ tốn phí mỗi lần bạn bấm. Tên mô hình đặt bằng `AI_MODEL` trong `.env`.

## 7. Cấu trúc dự án

```
app/
  data_providers/   kết nối API bóng đá (base.py = giao diện chung; football_data_org.py)
  database/         schema.py, db.py, repository.py (toàn bộ SQL ở đây)
  services/         đồng bộ, phân tích trận, dự đoán + chấm điểm + backtest
  analytics/        stats.py (phong độ, sân nhà/khách, đối đầu), conclusions.py
  prediction/       poisson.py (mô hình Poisson + Dixon-Coles), live.py (dự đoán trực tiếp + mô phỏng), evaluation.py (Brier, log loss...)
  ai_analysis/      writer.py (module AI tùy chọn)
  api/              routes.py (endpoint FastAPI)
  main.py, config.py
frontend/           index.html, styles.css, app.js (không cần build)
tests/              76 test; fixtures.py là DỮ LIỆU GIẢ chỉ dùng kiểm thử
scripts/            seed_test_data.py
```

Điều chỉnh so với đề bài, có lý do:
- **Không dùng pandas/NumPy**: các phép tính chỉ cần thư viện chuẩn Python, ít cài đặt hơn trên Windows.
- **`team_form` và `head_to_head` không có bảng riêng**: luôn tính lại từ `matches` tại đúng thời điểm trận, tránh dữ liệu cũ và rò rỉ tương lai. Thêm bảng `standings` cho trang xếp hạng.
- **Biểu đồ vẽ bằng HTML/CSS thuần** (dải xác suất, ma trận tỷ số), không cần thư viện ngoài.
- **sqlite3 chuẩn thay vì ORM**: SQL gom trong `repository.py` (dùng `ON CONFLICT` chuẩn). Chuyển PostgreSQL = viết lại lớp này (đổi `?` thành `%s`, `AUTOINCREMENT` thành `SERIAL`) mà không đụng phần còn lại.

Đổi nhà cung cấp dữ liệu: viết lớp mới kế thừa `FootballDataProvider` (3 phương thức) trong `data_providers/` và truyền vào `build_container` trong `main.py`.

## 8. Kiểm thử

Chạy `test.bat` (hoặc `pytest -q`). Bộ test dùng dữ liệu giả có gắn cờ và phản hồi API giả (httpx MockTransport); chưa có test nào gọi API football-data.org thật.

Muốn xem thử giao diện khi chưa có khóa: chạy `demo_test_data.bat`. Website sẽ dùng `data/test.db` với dữ liệu giả và hiện banner đỏ **DỮ LIỆU KIỂM THỬ** ở mọi trang. Dữ liệu này không bao giờ lẫn vào `football.db`.

## 9. Xử lý lỗi thường gặp

| Hiện tượng | Cách xử lý |
|---|---|
| "Chưa có khóa API" | Trang Cài đặt → dán khóa → Lưu |
| "API từ chối khóa (401)" | Khóa sai/thiếu ký tự; chép lại từ email |
| "không có quyền truy cập (403)" | Giải đó không nằm trong gói của bạn; bỏ chọn ở Cài đặt |
| "vượt giới hạn (429)" | Đợi 1–2 phút rồi thử lại; đừng bấm Ép cập nhật liên tục |
| "Không kết nối được" | Kiểm tra Internet; xem cửa sổ `start.bat` còn mở |
| "Chưa đủ dữ liệu" khi dự đoán | Đầu mùa/ít trận; đồng bộ thêm hoặc đợi vài vòng |
| Cổng 8000 bận | `python run.py --port 8001` |
| Quên khóa nằm ở đâu | File `.env` trong thư mục dự án (đã nằm trong `.gitignore`) |

## 10. Bảo mật

Khóa API chỉ đọc từ `.env`/biến môi trường, không bao giờ trả về trình duyệt (chỉ hiện 4 ký tự cuối). Đổi khóa chỉ cho phép từ localhost. Đầu vào API được kiểm tra; mọi lời gọi ra ngoài có timeout. Muốn công khai sau này cần thêm: đăng nhập, HTTPS, PostgreSQL, hàng đợi tác vụ nền (hiện dùng luồng nền đơn giản).
