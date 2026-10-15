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

Mô hình Poisson (`app/prediction/poisson.py`): từ các trận đã kết thúc của giải trong 400 ngày trước trận (trọng số giảm dần theo thời gian), tính tấn công/phòng ngự **riêng sân nhà và sân khách** của mỗi đội, co về mức trung bình giải để tránh mẫu nhỏ, suy ra bàn thắng kỳ vọng λ của hai đội, dựng ma trận tỷ số Poisson rồi cộng thành xác suất thắng/hòa/thua (làm tròn sao cho tổng đúng 100%).

- Chỉ dùng trận **đã kết thúc trước giờ bóng lăn**; kết quả tương lai không bao giờ lọt vào.
- Thiếu dữ liệu (dưới 6 trận mỗi đội hoặc dưới 40 trận của giải) → hiện cảnh báo, **không tạo dự đoán**.
- Dự đoán được **lưu trước trận** (kèm thời điểm) khi bạn mở trang trận hoặc sau mỗi lần đồng bộ; không bao giờ ghi đè hay xóa. Khi có kết quả thật, hệ thống chấm điểm tự động. Trang Lịch sử dự đoán hiển thị cả dự đoán sai.
- "Kiểm tra lại trên trận cũ" (backtest) chạy mô hình trên các trận đã đá chỉ bằng dữ liệu trước trận đó, để đo chất lượng ngay khi chưa có nhiều dự đoán thật. Kết quả này tách riêng, không trộn với dự đoán thật.
- Mô hình **không biết** chấn thương, đội hình, động lực, thời tiết. Hãy coi đây là công cụ tham khảo, không phải lời khuyên cá cược.

## 6. AI viết bài (tùy chọn)

Để trống thì mọi thứ vẫn chạy. Nếu thêm `ANTHROPIC_API_KEY` vào `.env`, trang trận sẽ có nút **Viết bài bằng AI**: hệ thống gửi cho AI một bản JSON số liệu đã tính, yêu cầu viết bài tiếng Việt và cấm thêm thông tin ngoài bản đó. Bài được lưu kèm thời điểm và mã dữ liệu; khi dữ liệu đổi sẽ báo "bài đã cũ" để tạo lại. Chỉ tốn phí mỗi lần bạn bấm. Tên mô hình đặt bằng `AI_MODEL` trong `.env`.

## 7. Cấu trúc dự án

```
app/
  data_providers/   kết nối API bóng đá (base.py = giao diện chung; football_data_org.py)
  database/         schema.py, db.py, repository.py (toàn bộ SQL ở đây)
  services/         đồng bộ, phân tích trận, dự đoán + chấm điểm + backtest
  analytics/        stats.py (phong độ, sân nhà/khách, đối đầu), conclusions.py
  prediction/       poisson.py (mô hình), evaluation.py (Brier, log loss...)
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
