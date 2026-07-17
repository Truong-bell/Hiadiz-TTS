import asyncio
import base64
import re
from io import BytesIO

import nest_asyncio
import requests
import streamlit as st
from pydub import AudioSegment

nest_asyncio.apply()  # tránh lỗi "event loop already running" khi deploy

import edge_tts
from gtts import gTTS
import speech_recognition as sr
import PyPDF2
import docx

st.set_page_config(page_title="TTS / STT / Voice Cloning", page_icon="🔊", layout="centered")
st.title("🔊 TTS / STT / Voice Cloning")

LUVVOICE_BASE = "https://luvvoice.com/api/v1/text-to-speech"

# gTTS chỉ hỗ trợ mã ngôn ngữ đơn giản (không phân biệt giọng)
GTTS_LANGS = {
    "Tiếng Việt": "vi", "English": "en", "日本語": "ja", "한국어": "ko",
    "中文 (Giản thể)": "zh-CN", "Français": "fr", "Deutsch": "de", "Español": "es",
    "Italiano": "it", "Português": "pt", "ไทย": "th", "Bahasa Indonesia": "id",
    "Русский": "ru", "العربية": "ar", "हिन्दी": "hi",
}

# STT (Google Web Speech) dùng mã bcp-47 đầy đủ
STT_LANGS = {
    "Tiếng Việt": "vi-VN", "English (US)": "en-US", "日本語": "ja-JP", "한국어": "ko-KR",
    "中文": "zh-CN", "Français": "fr-FR", "Deutsch": "de-DE", "Español": "es-ES",
    "Italiano": "it-IT", "Português": "pt-BR", "ไทย": "th-TH", "Bahasa Indonesia": "id-ID",
    "Русский": "ru-RU", "العربية": "ar-SA", "हिन्दी": "hi-IN",
}

# ------------------------------------------------------------------
# TIỆN ÍCH DÙNG CHUNG
# ------------------------------------------------------------------

def split_text(text: str, max_chars: int):
    """Chia văn bản dài thành từng đoạn nhỏ theo câu, không vượt quá max_chars."""
    sentences = re.split(r"(?<=[.!?\n])\s+", text.strip())
    chunks, current = [], ""
    for s in sentences:
        if not s:
            continue
        if len(current) + len(s) + 1 <= max_chars:
            current = f"{current} {s}".strip()
        else:
            if current:
                chunks.append(current)
            while len(s) > max_chars:
                chunks.append(s[:max_chars])
                s = s[max_chars:]
            current = s
    if current:
        chunks.append(current)
    return chunks or [text[:max_chars]]


@st.cache_data(ttl=86400, show_spinner=False)
def get_edge_voices():
    try:
        voices = asyncio.run(edge_tts.list_voices())
        return sorted(voices, key=lambda v: (v["Locale"], v["ShortName"]))
    except Exception:
        return []


def edge_tts_synthesize(text, voice, rate="+0%", volume="+0%", pitch="+0Hz"):
    async def _run():
        communicate = edge_tts.Communicate(text, voice, rate=rate, volume=volume, pitch=pitch)
        buf = BytesIO()
        async for chunk in communicate.stream():
            if chunk["type"] == "audio":
                buf.write(chunk["data"])
        buf.seek(0)
        return buf
    try:
        return asyncio.run(_run()), None
    except Exception as e:
        return None, f"Lỗi Edge TTS: {e}"


def gtts_synthesize(text, lang, slow=False):
    try:
        tts = gTTS(text=text, lang=lang, slow=slow)
        buf = BytesIO()
        tts.write_to_fp(buf)
        buf.seek(0)
        return buf, None
    except Exception as e:
        return None, f"Lỗi gTTS: {e}"


@st.cache_data(ttl=3600, show_spinner=False)
def luvvoice_get_voices(token, cloned=False):
    headers = {"Authorization": f"Bearer {token}"}
    params = {"action": "voices"}
    if cloned:
        params["type"] = "cloned"
    try:
        r = requests.get(LUVVOICE_BASE, headers=headers, params=params, timeout=15)
        if r.status_code != 200:
            return [], f"HTTP {r.status_code}: {r.text[:200]}"
        return r.json().get("voices", []), None
    except requests.exceptions.RequestException as e:
        return [], f"Lỗi kết nối LuvVoice: {e}"


def luvvoice_synthesize(token, text, voice_id, voice_type="standard", rate=0, pitch=0, volume=0):
    headers = {"Authorization": f"Bearer {token}", "Content-Type": "application/json"}
    payload = {"text": text, "voice_id": voice_id, "voice_type": voice_type,
               "rate": rate, "pitch": pitch, "volume": volume}
    try:
        r = requests.post(LUVVOICE_BASE, headers=headers, json=payload, timeout=30)
        if r.status_code != 200:
            try:
                err = r.json().get("error", r.text)
            except Exception:
                err = r.text
            return None, f"LuvVoice lỗi ({r.status_code}): {err}"
        data = r.json()
        if data.get("audio_data"):
            return BytesIO(base64.b64decode(data["audio_data"])), None
        if data.get("audio_url"):
            r2 = requests.get(data["audio_url"], timeout=30)
            r2.raise_for_status()
            return BytesIO(r2.content), None
        return None, "LuvVoice không trả về audio."
    except requests.exceptions.RequestException as e:
        return None, f"Lỗi kết nối LuvVoice: {e}"


def synthesize_long_text(text, engine, **kwargs):
    """Chia nhỏ văn bản dài, tổng hợp từng đoạn rồi ghép lại thành 1 file mp3.
    Luôn trả về (BytesIO | None, error | None) — không bao giờ raise để tránh crash app."""
    max_chars = 3000 if engine == "luvvoice" else 4500
    chunks = split_text(text, max_chars)
    combined = AudioSegment.empty()
    for chunk in chunks:
        if not chunk.strip():
            continue
        if engine == "gtts":
            buf, err = gtts_synthesize(chunk, kwargs.get("lang", "vi"), kwargs.get("slow", False))
        elif engine == "edge":
            buf, err = edge_tts_synthesize(chunk, kwargs.get("voice"), kwargs.get("rate", "+0%"),
                                            kwargs.get("volume", "+0%"), kwargs.get("pitch", "+0Hz"))
        elif engine == "luvvoice":
            buf, err = luvvoice_synthesize(kwargs.get("token"), chunk, kwargs.get("voice_id"),
                                            kwargs.get("voice_type", "standard"), kwargs.get("rate_n", 0),
                                            kwargs.get("pitch_n", 0), kwargs.get("volume_n", 0))
        else:
            return None, "Engine không hợp lệ."
        if err:
            return None, err
        try:
            combined += AudioSegment.from_file(buf, format="mp3")
        except Exception as e:
            return None, f"Lỗi ghép audio: {e}"
    out = BytesIO()
    combined.export(out, format="mp3")
    out.seek(0)
    return out, None


def extract_text_from_file(f):
    if f.name.endswith(".txt"):
        return f.read().decode("utf-8", errors="ignore")
    if f.name.endswith(".pdf"):
        reader = PyPDF2.PdfReader(f)
        return "\n".join(page.extract_text() or "" for page in reader.pages)
    if f.name.endswith(".docx"):
        d = docx.Document(f)
        return "\n".join(p.text for p in d.paragraphs)
    return ""


# ------------------------------------------------------------------
# SIDEBAR: CHỌN ENGINE
# ------------------------------------------------------------------

st.sidebar.header("⚙️ Cấu hình giọng nói")
engine_label = st.sidebar.radio(
    "Chọn engine TTS:",
    ["Edge TTS (Microsoft) — miễn phí, nhiều giọng", "Google TTS (gTTS) — miễn phí",
     "LuvVoice — cần API key riêng, hỗ trợ voice cloning"],
)
engine = {"Google TTS (gTTS) — miễn phí": "gtts",
          "Edge TTS (Microsoft) — miễn phí, nhiều giọng": "edge",
          "LuvVoice — cần API key riêng, hỗ trợ voice cloning": "luvvoice"}[engine_label]

luvvoice_token = ""
if engine == "luvvoice":
    luvvoice_token = st.sidebar.text_input("LuvVoice API Token", type="password",
                                            help="Lấy tại luvvoice.com/dashboard/api-tokens (cần gói Plus trở lên).")
    st.sidebar.caption("Token chỉ lưu trong phiên làm việc này, không được lưu lại.")

st.sidebar.divider()
st.sidebar.caption(
    "💡 gTTS và Edge TTS chạy hoàn toàn trên server của Google/Microsoft nên nhẹ, "
    "không tốn tài nguyên máy chủ — phù hợp để deploy free mà không lo lỗi server."
)

page = st.radio(
    "Chọn chức năng:",
    ["📝 Text → Speech", "🎙️ Speech → Text", "📄 File → Speech", "🧬 Voice Cloning"],
    horizontal=True, label_visibility="collapsed",
)
st.divider()

# ---------- TEXT TO SPEECH ----------
if page == "📝 Text → Speech":
    st.subheader("Chuyển văn bản thành giọng nói")
    text_input = st.text_area("Nhập văn bản:", height=150, placeholder="Nhập nội dung cần đọc...", key="t1_text")

    tts_kwargs = {}
    if engine == "gtts":
        lang_name = st.selectbox("Ngôn ngữ:", list(GTTS_LANGS.keys()), key="t1_gtts_lang")
        slow = st.checkbox("Đọc chậm", value=False, key="t1_gtts_slow")
        tts_kwargs = {"lang": GTTS_LANGS[lang_name], "slow": slow}

    elif engine == "edge":
        voices = get_edge_voices()
        if not voices:
            st.error("Không tải được danh sách giọng Edge TTS. Kiểm tra kết nối mạng và thử lại.")
        else:
            locales = sorted(set(v["Locale"] for v in voices))
            default_idx = locales.index("vi-VN") if "vi-VN" in locales else 0
            locale = st.selectbox("Ngôn ngữ:", locales, index=default_idx, key="t1_edge_locale")
            filtered = [v for v in voices if v["Locale"] == locale]
            voice_display = {f'{v["ShortName"].split("-")[-1].replace("Neural","")} ({v["Gender"]})': v["ShortName"]
                              for v in filtered}
            voice_choice = st.selectbox("Giọng đọc:", list(voice_display.keys()), key="t1_edge_voice")
            col1, col2, col3 = st.columns(3)
            rate_pct = col1.slider("Tốc độ (%)", -50, 50, 0, key="t1_edge_rate")
            volume_pct = col2.slider("Âm lượng (%)", -50, 50, 0, key="t1_edge_vol")
            pitch_hz = col3.slider("Cao độ (Hz)", -50, 50, 0, key="t1_edge_pitch")
            tts_kwargs = {"voice": voice_display[voice_choice], "rate": f"{rate_pct:+d}%",
                          "volume": f"{volume_pct:+d}%", "pitch": f"{pitch_hz:+d}Hz"}

    elif engine == "luvvoice":
        if not luvvoice_token:
            st.warning("Nhập API token của LuvVoice ở thanh bên trái để dùng engine này.")
        else:
            use_cloned = st.checkbox("Dùng giọng đã clone (voice cloning)", key="t1_luv_cloned")
            lv_voices, err = luvvoice_get_voices(luvvoice_token, cloned=use_cloned)
            if err:
                st.error(err)
            elif not lv_voices:
                st.info("Chưa có giọng nào." if use_cloned else "Không lấy được danh sách giọng.")
            else:
                voice_display = {f'{v["name"]} — {v.get("language_name", v.get("language",""))} ({v["gender"]})':
                                  v["voice_id"] for v in lv_voices}
                voice_choice = st.selectbox("Giọng đọc:", list(voice_display.keys()), key="t1_luv_voice")
                col1, col2, col3 = st.columns(3)
                rate_n = col1.slider("Tốc độ", -50, 50, 0, key="t1_luv_rate")
                pitch_n = col2.slider("Cao độ", -50, 50, 0, key="t1_luv_pitch")
                volume_n = col3.slider("Âm lượng", -50, 50, 0, key="t1_luv_vol")
                tts_kwargs = {"token": luvvoice_token, "voice_id": voice_display[voice_choice],
                              "voice_type": "cloned" if use_cloned else "standard",
                              "rate_n": rate_n, "pitch_n": pitch_n, "volume_n": volume_n}

    if st.button("🔊 Tạo giọng nói", type="primary", key="t1_btn"):
        if not text_input.strip():
            st.warning("Vui lòng nhập văn bản.")
        elif engine == "luvvoice" and not luvvoice_token:
            st.warning("Cần nhập API token LuvVoice trước.")
        else:
            with st.spinner("Đang tạo audio..."):
                buf, err = synthesize_long_text(text_input, engine, **tts_kwargs)
            if err:
                st.error(err)
            else:
                st.audio(buf, format="audio/mp3")
                st.download_button("⬇️ Tải file MP3", data=buf, file_name="speech.mp3", mime="audio/mp3", key="t1_dl")

# ---------- SPEECH TO TEXT ----------
elif page == "🎙️ Speech → Text":
    st.subheader("Chuyển giọng nói thành văn bản")
    st.caption("Tải lên file âm thanh (wav, mp3, m4a...) để nhận dạng. Dùng Google Speech Recognition (miễn phí, cần internet).")
    audio_file = st.file_uploader("Chọn file audio", type=["wav", "mp3", "m4a", "ogg", "flac"], key="t2_upload")
    stt_lang_name = st.selectbox("Ngôn ngữ audio:", list(STT_LANGS.keys()), key="t2_lang")

    if audio_file is not None:
        st.audio(audio_file)
        if st.button("🎙️ Nhận dạng giọng nói", type="primary", key="t2_btn"):
            with st.spinner("Đang xử lý..."):
                try:
                    audio = AudioSegment.from_file(audio_file)
                    wav_io = BytesIO()
                    audio.export(wav_io, format="wav")
                    wav_io.seek(0)
                    r = sr.Recognizer()
                    with sr.AudioFile(wav_io) as source:
                        audio_data = r.record(source)
                    result_text = r.recognize_google(audio_data, language=STT_LANGS[stt_lang_name])
                    st.success("Kết quả:")
                    st.write(result_text)
                    st.download_button("⬇️ Tải văn bản (.txt)", data=result_text.encode("utf-8"),
                                        file_name="transcript.txt", mime="text/plain", key="t2_dl")
                except sr.UnknownValueError:
                    st.error("Không nhận dạng được giọng nói trong file này.")
                except sr.RequestError as e:
                    st.error(f"Lỗi kết nối tới dịch vụ nhận dạng: {e}. Thử lại sau.")
                except Exception as e:
                    st.error(f"Lỗi xử lý file audio: {e}")

# ---------- FILE TO SPEECH ----------
elif page == "📄 File → Speech":
    st.subheader("Chuyển file văn bản thành giọng nói")
    doc_file = st.file_uploader("Chọn file (.txt, .pdf, .docx)", type=["txt", "pdf", "docx"], key="t3_upload")

    file_kwargs = {}
    if engine == "gtts":
        f_lang_name = st.selectbox("Ngôn ngữ:", list(GTTS_LANGS.keys()), key="t3_gtts_lang")
        file_kwargs = {"lang": GTTS_LANGS[f_lang_name]}
    elif engine == "edge":
        voices = get_edge_voices()
        if voices:
            locales = sorted(set(v["Locale"] for v in voices))
            default_idx = locales.index("vi-VN") if "vi-VN" in locales else 0
            locale = st.selectbox("Ngôn ngữ:", locales, index=default_idx, key="t3_edge_locale")
            filtered = [v for v in voices if v["Locale"] == locale]
            voice_display = {f'{v["ShortName"].split("-")[-1].replace("Neural","")} ({v["Gender"]})': v["ShortName"]
                              for v in filtered}
            voice_choice = st.selectbox("Giọng đọc:", list(voice_display.keys()), key="t3_edge_voice")
            file_kwargs = {"voice": voice_display[voice_choice]}
    elif engine == "luvvoice":
        if not luvvoice_token:
            st.warning("Nhập API token của LuvVoice ở thanh bên trái để dùng engine này.")
        else:
            use_cloned = st.checkbox("Dùng giọng đã clone", key="t3_luv_cloned")
            lv_voices, err = luvvoice_get_voices(luvvoice_token, cloned=use_cloned)
            if err:
                st.error(err)
            elif lv_voices:
                voice_display = {f'{v["name"]} — {v.get("language_name", v.get("language",""))} ({v["gender"]})':
                                  v["voice_id"] for v in lv_voices}
                voice_choice = st.selectbox("Giọng đọc:", list(voice_display.keys()), key="t3_luv_voice")
                file_kwargs = {"token": luvvoice_token, "voice_id": voice_display[voice_choice],
                               "voice_type": "cloned" if use_cloned else "standard"}

    if doc_file is not None:
        extracted = extract_text_from_file(doc_file)
        st.text_area("Nội dung trích xuất:", value=extracted, height=200, key="t3_preview")

        if st.button("🔊 Tạo giọng nói từ file", type="primary", key="t3_btn"):
            if not extracted.strip():
                st.warning("Không trích xuất được nội dung từ file.")
            elif engine == "luvvoice" and not luvvoice_token:
                st.warning("Cần nhập API token LuvVoice trước.")
            else:
                with st.spinner("Đang tạo audio (file dài có thể mất vài phút)..."):
                    buf, err = synthesize_long_text(extracted, engine, **file_kwargs)
                if err:
                    st.error(err)
                else:
                    st.audio(buf, format="audio/mp3")
                    st.download_button("⬇️ Tải file MP3", data=buf, file_name="file_speech.mp3",
                                        mime="audio/mp3", key="t3_dl")

# ---------- VOICE CLONING ----------
elif page == "🧬 Voice Cloning":
    st.subheader("🧬 Voice Cloning")
    st.markdown(
        """
Việc **tạo giọng clone thật sự** (từ mẫu giọng của bạn) đòi hỏi model AI rất nặng
(GPU, nhiều RAM). Chạy trực tiếp model đó trên hosting miễn phí (Streamlit Cloud, Render free...)
gần như chắc chắn sẽ bị treo hoặc lỗi server do hết bộ nhớ.

Vì vậy app này **không tự chạy model clone giọng cục bộ**, mà dùng dịch vụ cloud
của **LuvVoice** để việc tính toán nặng diễn ra trên server của họ — app của bạn chỉ gọi API,
nên không lo bị crash.

**Cách dùng:**
1. Tạo tài khoản tại [luvvoice.com](https://luvvoice.com) và nâng cấp gói **Plus** (yêu cầu để dùng API).
2. Vào [luvvoice.com/voice-cloning](https://luvvoice.com/voice-cloning), upload mẫu giọng của bạn và tạo voice clone (bước này làm trên web LuvVoice, chưa có API public để tạo clone).
3. Lấy API token tại [Dashboard → API Tokens](https://luvvoice.com/dashboard/api-tokens), dán vào thanh bên trái, chọn engine **LuvVoice**.
4. Quay lại tab **Text → Speech** hoặc **File → Speech**, tick **"Dùng giọng đã clone"** để chọn giọng của bạn.
        """
    )
    if luvvoice_token:
        _, err = luvvoice_get_voices(luvvoice_token, cloned=True)
        if err:
            st.error(err)
        else:
            st.success("Đã kết nối LuvVoice — vào tab Text → Speech hoặc File → Speech và tick 'Dùng giọng đã clone'.")

st.divider()
st.caption("Made with Streamlit · gTTS · Edge TTS · LuvVoice API · SpeechRecognition")
