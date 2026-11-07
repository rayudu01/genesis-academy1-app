# Genesis Academy – Student Result & Performance Tracking System

Complete working Streamlit app for student performance tracking, AI answer-sheet evaluation (OCR + Multimodal LLM), PDF report cards, parent WhatsApp sharing, and more.

## Live Demo / Deploy

**Recommended free hosting:** [Streamlit Community Cloud](https://share.streamlit.io)

### Deploy in 5 minutes

1. Fork or upload this repository to your GitHub account.
2. Go to → https://share.streamlit.io
3. Sign in with GitHub.
4. Click **Create app**.
5. Select this repository → Main file path: `app.py`
6. Click **Deploy**.

Your app will be live at: `https://your-app-name.streamlit.app`

### Optional Secrets (for Multimodal LLM & WhatsApp)

In Streamlit Cloud → App settings → Secrets, add:

```toml
OPENAI_API_KEY = "sk-..."
# or
XAI_API_KEY = "xai-..."

TWILIO_ACCOUNT_SID = "AC..."
TWILIO_AUTH_TOKEN = "..."
TWILIO_WHATSAPP_FROM = "whatsapp:+14155238886"
```

## Features

- Student management
- Exam + Syllabus + CBSE-style rubric
- Answer sheet photo upload + OCR
- **True Multimodal AI evaluation** (gpt-4o or xAI Grok vision)
- Teacher score override
- Bulk evaluation
- PDF Report Cards
- Weekly / Fortnight / Monthly performance tracking
- Individual & Batch timetable generator
- Parent WhatsApp message generation + Twilio ready

## Local Run

```bash
pip install -r requirements.txt
streamlit run app.py
```

## Project Structure

```
├── app.py                 # Main application
├── requirements.txt
├── .streamlit/config.toml
├── data/                  # SQLite database (auto-created)
├── uploads/               # Answer sheet images
└── reports/               # Generated PDF report cards
```

## Notes

- Tesseract OCR is used locally. On Streamlit Cloud the local OCR still works for text extraction; for best handwriting accuracy use the Multimodal LLM option.
- Database is SQLite (file-based). For production with many users consider PostgreSQL later.

Built for Genesis Academy.
