# KỊCH BẢN TRÌNH BÀY DEMO BUỔI 6
## Nhóm A7: Notification Service (Product A)

Dưới đây là kịch bản trình bày chi tiết bám sát **6 bước** và **tiêu chí chấm điểm** của giảng viên. Bạn có thể mở file này để đọc trực tiếp khi thuyết trình.

---

### 1. VAI TRÒ CỦA NHÓM (1.0 điểm)
* **Tên Dịch Vụ:** Notification Service (Dịch vụ gửi cảnh báo).
* **Vai trò trong hệ thống Smart Campus:** 
  * Tiếp nhận các sự kiện cảnh báo từ hệ thống và gửi thông báo đa kênh đến người dùng cuối.
  * Là **Provider** (Bên cung cấp dịch vụ) đối với dịch vụ **Core Business (nhóm A6)**. Nhóm A6 đóng vai trò là Consumer sẽ chủ động gọi API sang nhóm em.

---

### 2. INPUT (DỮ LIỆU ĐẦU VÀO)
* **Dữ liệu nhận vào:** Sự kiện cảnh báo dạng JSON Payload qua giao thức **REST API** (HTTP POST).
* **Nguồn gửi:** Nhận từ dịch vụ **Core Business (A6)**.
* **Các Endpoint tiếp nhận:**
  * `POST /events/alert.created` (Khi có cảnh báo mới).
  * `POST /events/alert.escalated` (Khi cảnh báo leo thang).
  * `POST /events/alert.resolved` (Khi cảnh báo được xử lý xong).
* **Cấu trúc JSON Input mẫu:**
  ```json
  {
    "eventId": "550e8400-e29b-41d4-a716-446655440000",
    "eventType": "alert.created",
    "alertId": "ALT-2026-05-19-001",
    "correlationId": "COR-2026-05-19-001",
    "source": "core-business-service",
    "severity": "HIGH",
    "alertVersion": 1,
    "payload": {
      "title": "Truy cập trái phép",
      "message": "Phát hiện chuyển động lạ tại cổng chính"
    },
    "channels": ["telegram", "email", "app"]
  }
  ```

---

### 3. XỬ LÝ NGHIỆP VỤ (1.0 điểm & Xử lý lỗi 1.0 điểm)
Khi nhận được request từ nhóm A6, dịch vụ tiến hành xử lý qua các bước:
1. **Xác thực:** Kiểm tra mã bảo mật ở Header `Authorization: Bearer local-dev-token`.
2. **Validate Schema:** Kiểm tra cấu trúc JSON đầu vào, bắt buộc `eventId` phải đúng định dạng **UUID**. Nếu sai sẽ trả về lỗi `422 Unprocessable Entity` (chuẩn RFC 7807).
3. **Phân tích thông minh (AI Integration):** Gọi API sang dịch vụ **AI Service** (`/predict` trên port 9000) để phân tích mức độ cảnh báo (YOLO model).
4. **Phân phối đa kênh:** Duyệt qua mảng `channels` yêu cầu (tối đa 4 kênh). Với mỗi kênh, hệ thống ghi nhận lịch sử gửi vào cơ sở dữ liệu **PostgreSQL**.
5. **Xử lý lỗi / Timeout:**
   * Các cuộc gọi sang AI Service hoặc kết nối Database được cấu hình **Timeout tối đa 2.0 giây** để tránh treo request vô hạn.
   * Nếu Database PostgreSQL gặp sự cố, hệ thống có cơ chế **Fallback tự động lưu vào bộ nhớ tạm (In-memory dict)**, đảm bảo API vẫn trả về thành công cho nhóm đối tác mà không bị crash.

---

### 4. OUTPUT (DỮ LIỆU ĐẦU RA)
* **Kết quả trả về:** Dịch vụ phản hồi mã trạng thái HTTP **`202 Accepted`** (xác nhận đã tiếp nhận và xếp hàng gửi).
* **JSON Output mẫu:**
  ```json
  {
    "eventId": "550e8400-e29b-41d4-a716-446655440000",
    "status": "queued",
    "processedAt": "2026-06-17T17:23:39.220091+00:00"
  }
  ```

---

### 5. OUTPUT GỬI CHO AI?
* Dịch vụ Notification là **điểm cuối của luồng tích hợp** (chịu trách nhiệm trực tiếp đẩy thông báo đến các ứng dụng Telegram, Email, App của người dùng cuối), nên nhóm em **không gửi tiếp output sang dịch vụ nào khác** trong hệ thống Smart Campus.

---

### 6. MINH CHỨNG DEMO (1.5 điểm)
*(Show trực tiếp cho thầy xem)*

1. **Giao diện Web Dashboard:** Mở trình duyệt vào **`http://localhost:8000/`**.
   * Show trạng thái của **Notification API, PostgreSQL Database, AI Service** đều báo màu xanh lá cây (`HEALTHY`).
   * Show bảng lịch sử thông báo lấy real-time từ Database.
2. **Kiểm thử tích hợp (Bắt tay thật):**
   * Nhờ nhóm A6 (Core Business) thực hiện bắn thử sự kiện từ máy của họ qua **Radmin IP** của bạn.
   * Chỉ cho thầy xem dòng thông báo mới xuất hiện ngay lập tức trên bảng **Real-time Notifications Log** mà không cần reload trang.
3. **Container Status:** Mở Terminal chạy `docker compose ps` để show toàn bộ container đang chạy bình thường.
