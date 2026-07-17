# TTS / STT / Voice Cloning App (Streamlit)

Ứng dụng web với 4 chức năng:
- **Text → Speech**: nhập văn bản, chọn engine (gTTS / Edge TTS / LuvVoice), tạo file âm thanh.
- **Speech → Text**: tải lên file audio, nhận dạng thành văn bản (Google Speech Recognition, miễn phí).
- **File → Speech**: tải lên .txt / .pdf / .docx, đọc thành giọng nói, tự động chia nhỏ nếu văn bản dài.
- **Voice Cloning**: dùng giọng clone của bạn qua LuvVoice API (việc tính toán nặng chạy trên cloud của họ, không chạy trên máy/server của bạn).

## 3 engine TTS

| Engine | Chi phí | Ưu điểm | Cần gì |
|---|---|---|---|
| gTTS (Google) | Miễn phí | Đơn giản, ổn định | Không cần key |
| Edge TTS (Microsoft) | Miễn phí | Rất nhiều giọng & ngôn ngữ, giọng tự nhiên hơn gTTS | Không cần key |
| LuvVoice | Cần gói Plus trở lên | 200+ giọng, hỗ trợ **voice cloning** | API token riêng của bạn (luvvoice.com) |

Chọn engine ở thanh bên trái (sidebar). Nếu chọn LuvVoice, nhập API token của bạn (lấy tại `luvvoice.com/dashboard/api-tokens`) — token chỉ lưu trong phiên làm việc, không được ghi vào code hay lưu lại.

## Vì sao không có voice cloning tự chạy (self-hosted)?

Voice cloning "xịn" (nhân bản giọng từ mẫu audio) cần model AI rất nặng, đòi hỏi GPU/RAM lớn.
Chạy trực tiếp trên hosting miễn phí (Streamlit Community Cloud chỉ có ~1GB RAM, không GPU) gần như
chắc chắn sẽ crash hoặc timeout. App này dùng LuvVoice API để việc tính toán nặng diễn ra trên
server của họ, giữ app của bạn nhẹ và ổn định.

## Cài đặt

1. Cài Python 3.9+.
2. Cài **ffmpeg** (bắt buộc để xử lý audio với pydub):
   - macOS: `brew install ffmpeg`
   - Ubuntu/Debian: `sudo apt install ffmpeg`
   - Windows: tải từ https://ffmpeg.org và thêm vào PATH.
3. Cài các thư viện Python:
   ```bash
   pip install -r requirements.txt
   ```

## Chạy ứng dụng

```bash
streamlit run app.py
```

Trình duyệt sẽ tự mở tại `http://localhost:8501`.

## Deploy lên Streamlit Community Cloud (miễn phí, dùng được trên điện thoại)

1. Upload `app.py`, `requirements.txt`, `packages.txt` lên 1 repo GitHub.
2. Vào share.streamlit.io, đăng nhập GitHub, "New app", chọn repo, file chính là `app.py`.
3. Deploy — nhận link dạng `tenapp.streamlit.app`, mở được trên điện thoại như web bình thường.

## Lưu ý

- gTTS, Edge TTS và LuvVoice đều xử lý trên server bên ngoài, **cần kết nối internet**, và không tốn tài nguyên máy chủ của bạn — phù hợp để deploy free.
- STT dùng free API của Google nên có giới hạn số lượt gọi/ngày.
- LuvVoice: tài khoản free giới hạn 3.000 ký tự/request (app tự động chia nhỏ văn bản dài), cần gói Plus để có API token.
- Việc **tạo** voice clone mới hiện phải làm trên web `luvvoice.com/voice-cloning` (chưa có API public để tạo clone) — app chỉ dùng giọng đã clone sẵn.


