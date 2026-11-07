"""
Genesis Academy - Student Result & Performance Tracking System
Enhanced Full-stack Prototype v2.0

Features:
- AI Answer Sheet Evaluation (OCR + CBSE Rubric + optional Multimodal LLM)
- Teacher score override + bulk evaluation
- PDF Report Cards
- WhatsApp Business / Twilio integration ready
- Performance tracking (weekly/fortnight/monthly)
- Timetables (individual + batch)
- Parent sharing
- Mobile-ready notes / PWA structure
"""

import streamlit as st
import sqlite3
import pandas as pd
from datetime import datetime, timedelta
import os
import json
import base64
from PIL import Image
import pytesseract
import io
import re
from pathlib import Path
from reportlab.lib.pagesizes import A4
from reportlab.lib.units import mm, inch
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.lib.enums import TA_CENTER, TA_LEFT, TA_RIGHT
from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer, Table, TableStyle, Image as RLImage
from reportlab.lib import colors
from reportlab.lib.colors import HexColor
import tempfile

# ==================== CONFIG ====================
st.set_page_config(
    page_title="Genesis Academy - Student Performance System v2",
    page_icon="🎓",
    layout="wide",
    initial_sidebar_state="expanded"
)

# Relative paths – works on Streamlit Community Cloud and locally
BASE_DIR = Path(__file__).parent.resolve()
UPLOAD_DIR = BASE_DIR / "uploads"
DATA_DIR = BASE_DIR / "data"
REPORTS_DIR = BASE_DIR / "reports"
DB_PATH = DATA_DIR / "genesis.db"

for d in [UPLOAD_DIR, DATA_DIR, REPORTS_DIR]:
    d.mkdir(parents=True, exist_ok=True)

# Optional API keys – works with Streamlit secrets + environment variables
def _get_secret(key, default=""):
    try:
        return st.secrets.get(key, os.getenv(key, default))
    except Exception:
        return os.getenv(key, default)

OPENAI_API_KEY = _get_secret("OPENAI_API_KEY", "")
XAI_API_KEY = _get_secret("XAI_API_KEY", "")
TWILIO_ACCOUNT_SID = _get_secret("TWILIO_ACCOUNT_SID", "")
TWILIO_AUTH_TOKEN = _get_secret("TWILIO_AUTH_TOKEN", "")
TWILIO_WHATSAPP_FROM = _get_secret("TWILIO_WHATSAPP_FROM", "whatsapp:+14155238886")

# ==================== DATABASE ====================
def get_conn():
    conn = sqlite3.connect(str(DB_PATH), check_same_thread=False)
    conn.row_factory = sqlite3.Row
    return conn

def init_db():
    conn = get_conn()
    c = conn.cursor()
    
    c.execute("""
    CREATE TABLE IF NOT EXISTS students (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        name TEXT NOT NULL,
        class TEXT,
        section TEXT,
        roll_no TEXT,
        parent_name TEXT,
        parent_phone TEXT,
        parent_whatsapp TEXT,
        batch TEXT,
        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
    )
    """)
    
    c.execute("""
    CREATE TABLE IF NOT EXISTS subjects (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        name TEXT UNIQUE,
        code TEXT
    )
    """)
    
    c.execute("""
    CREATE TABLE IF NOT EXISTS exams (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        name TEXT NOT NULL,
        subject TEXT,
        class TEXT,
        exam_date DATE,
        max_marks REAL,
        syllabus_text TEXT,
        model_answer TEXT,
        rubric_json TEXT,
        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
    )
    """)
    
    c.execute("""
    CREATE TABLE IF NOT EXISTS answer_sheets (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        student_id INTEGER,
        exam_id INTEGER,
        image_path TEXT,
        ocr_text TEXT,
        score REAL,
        max_marks REAL,
        feedback TEXT,
        suggestions TEXT,
        practice_problems TEXT,
        status TEXT DEFAULT 'pending',
        teacher_override INTEGER DEFAULT 0,
        original_ai_score REAL,
        evaluated_at TIMESTAMP,
        FOREIGN KEY(student_id) REFERENCES students(id),
        FOREIGN KEY(exam_id) REFERENCES exams(id)
    )
    """)
    
    c.execute("""
    CREATE TABLE IF NOT EXISTS performance_logs (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        student_id INTEGER,
        subject TEXT,
        period_type TEXT,
        period_start DATE,
        period_end DATE,
        average_score REAL,
        remarks TEXT,
        shared_with_parent INTEGER DEFAULT 0,
        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
        FOREIGN KEY(student_id) REFERENCES students(id)
    )
    """)
    
    c.execute("""
    CREATE TABLE IF NOT EXISTS timetables (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        student_id INTEGER NULL,
        batch TEXT NULL,
        title TEXT,
        schedule_json TEXT,
        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
    )
    """)
    
    c.execute("""
    CREATE TABLE IF NOT EXISTS whatsapp_logs (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        student_id INTEGER,
        message TEXT,
        status TEXT,
        sent_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
    )
    """)
    
    # Seed if empty
    c.execute("SELECT COUNT(*) FROM students")
    if c.fetchone()[0] == 0:
        sample_students = [
            ("Aarav Sharma", "10", "A", "101", "Rajesh Sharma", "9876543210", "9876543210", "Batch-A"),
            ("Priya Patel", "10", "A", "102", "Suresh Patel", "9876543211", "9876543211", "Batch-A"),
            ("Rohan Kumar", "10", "B", "201", "Anita Kumar", "9876543212", "9876543212", "Batch-B"),
            ("Sneha Reddy", "9", "A", "301", "Venkat Reddy", "9876543213", "9876543213", "Batch-A"),
            ("Arjun Singh", "10", "A", "103", "Meera Singh", "9876543214", "9876543214", "Batch-A"),
        ]
        c.executemany(
            "INSERT INTO students (name, class, section, roll_no, parent_name, parent_phone, parent_whatsapp, batch) VALUES (?,?,?,?,?,?,?,?)",
            sample_students
        )
        
        subjects = [("Mathematics", "MATH"), ("Science", "SCI"), ("English", "ENG"), ("Social Science", "SST"), ("Hindi", "HIN")]
        c.executemany("INSERT INTO subjects (name, code) VALUES (?,?)", subjects)
        
        sample_rubric = json.dumps({
            "questions": [
                {"qno": "1", "max": 5, "keywords": ["photosynthesis", "chlorophyll", "sunlight", "carbon dioxide", "oxygen", "glucose", "stomata"], "type": "descriptive", "bloom": "Understand"},
                {"qno": "2", "max": 3, "keywords": ["newton", "force", "mass", "acceleration", "f=ma", "second law"], "type": "short", "bloom": "Apply"},
                {"qno": "3", "max": 2, "keywords": ["true", "false", "yes", "no"], "type": "mcq", "bloom": "Remember"}
            ],
            "liberal_marking": True,
            "cbse_notes": "Award partial marks for correct steps/keywords even if final answer incomplete. Neatness, structure and innovative correct answers get credit. Follow CBSE marking scheme strictly for value points but liberally for method."
        })
        
        c.execute("""
        INSERT INTO exams (name, subject, class, exam_date, max_marks, syllabus_text, model_answer, rubric_json)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?)
        """, (
            "Unit Test 1 - Science",
            "Science",
            "10",
            "2026-10-15",
            10,
            "Chapter 1: Photosynthesis\nChapter 2: Force and Laws of Motion\nBasic concepts, equations, applications and diagrams.",
            "1. Photosynthesis is the process by which green plants synthesise food (glucose) using sunlight, chlorophyll, carbon dioxide and water, releasing oxygen. Equation: 6CO2 + 6H2O → C6H12O6 + 6O2.\n2. Newton's second law: Force = mass × acceleration (F = ma). Unit of force is Newton.\n3. As per question (True/False).",
            sample_rubric
        ))
    
    conn.commit()
    conn.close()

init_db()

# ==================== OCR ====================
def perform_ocr(image_bytes):
    try:
        image = Image.open(io.BytesIO(image_bytes))
        if image.mode != 'RGB':
            image = image.convert('RGB')
        text = pytesseract.image_to_string(image, lang='eng', config='--psm 6')
        return text.strip()
    except Exception as e:
        return f"OCR Error: {str(e)}"

# ==================== ENHANCED AI GRADING ====================
def evaluate_with_rubric(ocr_text, rubric_json, model_answer, max_marks, use_llm=False, api_key=None, image_bytes_list=None):
    """
    Enhanced CBSE-aligned evaluation.
    Supports TRUE MULTIMODAL: if image_bytes_list provided + use_llm + api_key,
    sends the actual answer-sheet images to a vision model (gpt-4o / gpt-4o-mini).
    Falls back to OCR text + local rubric engine otherwise.
    """
    try:
        rubric = json.loads(rubric_json) if isinstance(rubric_json, str) else rubric_json
    except:
        rubric = {"questions": [], "liberal_marking": True}
    
    questions = rubric.get("questions", [])
    total_score = 0.0
    feedback_parts = []
    mistakes = []
    strengths = []
    ocr_lower = (ocr_text or "").lower()
    
    # ---- TRUE MULTIMODAL LLM path (OpenAI gpt-4o OR xAI Grok) ----
    if use_llm and api_key:
        try:
            from openai import OpenAI
            import base64
            
            # Auto-detect provider: xAI keys usually start with "xai-" 
            is_xai = api_key.strip().lower().startswith("xai-") or "x.ai" in api_key.lower()
            if is_xai:
                client = OpenAI(api_key=api_key, base_url="https://api.x.ai/v1")
                model_name = "grok-2-vision-1212"  # or latest Grok vision model
                source_label = "Multimodal LLM (xAI Grok vision)"
            else:
                client = OpenAI(api_key=api_key)
                model_name = "gpt-4o"
                source_label = "Multimodal LLM (gpt-4o vision)"
            
            system_prompt = f"""You are an expert CBSE board examiner with years of experience evaluating Class 9-12 answer sheets.
Evaluate strictly according to CBSE guidelines but apply LIBERAL / PARTIAL marking:
- Award marks for correct concepts, keywords, steps and method even if the final answer is incomplete or has calculation errors.
- Credit neat structure, diagrams, equations and underlining.
- Be fair to innovative but scientifically correct answers.

MODEL ANSWER / KEY POINTS:
{model_answer}

RUBRIC (JSON):
{json.dumps(rubric, indent=2)}

Maximum marks for this paper: {max_marks}

Return ONLY a valid JSON object with these keys:
- score (float)
- feedback (string, question-wise detailed feedback)
- suggestions (list of strings)
- practice_problems (list of strings)
- mistakes (list of strings)
"""
            # Build multimodal content
            content = [{"type": "text", "text": system_prompt + "\n\nBelow are the actual scanned pages of the student's answer sheet. Also OCR text is provided for reference.\n\nOCR TEXT (may contain errors):\n" + (ocr_text or "")[:3000]}]
            
            # Attach up to 4 images
            if image_bytes_list:
                for i, img_bytes in enumerate(image_bytes_list[:4]):
                    b64 = base64.b64encode(img_bytes).decode("utf-8")
                    mime = "image/jpeg"
                    if img_bytes[:8] == b'\x89PNG\r\n\x1a\n':
                        mime = "image/png"
                    content.append({
                        "type": "image_url",
                        "image_url": {
                            "url": f"data:{mime};base64,{b64}",
                            "detail": "high"
                        }
                    })
            
            resp = client.chat.completions.create(
                model=model_name,
                messages=[{"role": "user", "content": content}],
                temperature=0.15,
                max_tokens=2000,
                response_format={"type": "json_object"}
            )
            llm_result = json.loads(resp.choices[0].message.content)
            return {
                "score": float(llm_result.get("score", 0)),
                "feedback": llm_result.get("feedback", ""),
                "suggestions": "\n".join(f"• {s}" for s in llm_result.get("suggestions", [])),
                "practice_problems": "\n".join(llm_result.get("practice_problems", [])),
                "mistakes": llm_result.get("mistakes", []),
                "source": source_label
            }
        except Exception as e:
            st.warning(f"Multimodal LLM call failed ({e}). Falling back to local OCR + rubric engine.")
    
    # ---- Local strong rubric engine ----
    for q in questions:
        qno = q.get("qno", "?")
        qmax = float(q.get("max", 1))
        keywords = [k.lower() for k in q.get("keywords", [])]
        qtype = q.get("type", "descriptive")
        bloom = q.get("bloom", "Understand")
        
        matched = sum(1 for kw in keywords if kw in ocr_lower)
        coverage = matched / len(keywords) if keywords else 0.4
        
        if coverage >= 0.85:
            score = qmax
            strengths.append(f"Q{qno}: Strong conceptual coverage ({matched}/{len(keywords)}).")
        elif coverage >= 0.55:
            score = round(qmax * 0.75, 1)
            mistakes.append(f"Q{qno}: Good attempt but missing some key points ({matched}/{len(keywords)}).")
        elif coverage >= 0.25:
            score = round(qmax * 0.45, 1)
            mistakes.append(f"Q{qno}: Incomplete. Key concepts missing.")
        else:
            score = round(qmax * 0.15, 1) if coverage > 0.05 else 0.0
            mistakes.append(f"Q{qno}: Little relevant content.")
        
        if re.search(r'(\d+\.|step|therefore|hence|thus|because|equation|diagram)', ocr_lower):
            score = min(qmax, score + 0.3)
        
        if bloom in ["Apply", "Analyze", "Evaluate"] and coverage > 0.3:
            score = min(qmax, score + 0.2)
        
        total_score += score
        feedback_parts.append(
            f"**Q{qno}** ({score:.1f}/{qmax}) [{bloom}]: Matched {matched}/{len(keywords)} keywords. "
            f"{'Excellent.' if score >= qmax*0.8 else 'Needs more detail.' if score < qmax*0.5 else 'Satisfactory with room to improve.'}"
        )
    
    if not questions:
        model_words = set((model_answer or "").lower().split())
        common = len(set(ocr_lower.split()) & model_words)
        coverage = common / max(len(model_words), 1)
        total_score = min(max_marks, round(max_marks * (0.25 + coverage * 0.7), 1))
        feedback_parts.append(f"Overall conceptual overlap ~{coverage*100:.0f}%.")
    
    total_score = min(max_marks, round(total_score, 1))
    
    suggestions = []
    if mistakes:
        suggestions.append("Write complete answers covering all value points from the marking scheme.")
        suggestions.append("Underline keywords, formulas and final answers (CBSE examiners look for them).")
        suggestions.append("Show clear steps even if final numerical answer is wrong — partial marks are awarded.")
        for m in mistakes[:4]:
            suggestions.append(m)
    else:
        suggestions.append("Outstanding work. Maintain this standard and attempt higher-order application questions.")
    
    if total_score < max_marks * 0.55:
        suggestions.append("Revise the chapter thoroughly and practise writing model answers under timed conditions.")
    
    practice = []
    text_blob = (ocr_text + " " + str(mistakes)).lower()
    if any(k in text_blob for k in ["photo", "chloro", "glucose", "stomata"]):
        practice.extend([
            "1. Draw a neat labelled diagram of a chloroplast and explain the role of chlorophyll. (5 marks)",
            "2. Write the balanced chemical equation of photosynthesis and list any three factors affecting its rate. (4 marks)",
            "3. Differentiate between light reaction and dark reaction of photosynthesis. (3 marks)"
        ])
    if any(k in text_blob for k in ["force", "newton", "acceleration", "mass", "f=ma"]):
        practice.extend([
            "4. State Newton’s second law of motion. A force of 15 N produces an acceleration of 3 m/s². Find the mass of the body. Show steps. (3 marks)",
            "5. Explain inertia with two real-life examples. How is it related to mass? (3 marks)"
        ])
    if not practice:
        practice = [
            "1. Write a model answer for the highest-weightage question of this chapter (use points + diagram if needed).",
            "2. Solve 3 previous-year CBSE questions from this unit under 15 minutes.",
            "3. Make a one-page revision sheet of all formulas and key definitions."
        ]
    
    feedback = "\n\n".join(feedback_parts)
    feedback += f"\n\n**Total Score: {total_score} / {max_marks}**\n"
    feedback += f"\n**Strengths:** {' '.join(strengths) if strengths else 'Structure can be improved further.'}"
    feedback += f"\n**Areas to improve:** {' '.join(mistakes) if mistakes else 'None significant.'}"
    feedback += "\n\n*Evaluation follows CBSE liberal marking principles: partial credit for correct method/concepts.*"
    
    return {
        "score": total_score,
        "feedback": feedback,
        "suggestions": "\n".join(f"• {s}" for s in suggestions),
        "practice_problems": "\n".join(practice),
        "mistakes": mistakes,
        "source": "Local Rubric Engine"
    }

# ==================== PDF REPORT CARD ====================
def generate_pdf_report_card(student_row, sheets_df, performance_df, output_path):
    doc = SimpleDocTemplate(
        str(output_path),
        pagesize=A4,
        rightMargin=15*mm,
        leftMargin=15*mm,
        topMargin=15*mm,
        bottomMargin=15*mm
    )
    styles = getSampleStyleSheet()
    
    title_style = ParagraphStyle(
        'TitleCustom', parent=styles['Heading1'], fontSize=18, alignment=TA_CENTER,
        textColor=HexColor("#1a365d"), spaceAfter=6
    )
    subtitle = ParagraphStyle(
        'Sub', parent=styles['Normal'], fontSize=11, alignment=TA_CENTER, spaceAfter=12
    )
    heading = ParagraphStyle(
        'H', parent=styles['Heading2'], fontSize=13, textColor=HexColor("#2c5282"), spaceBefore=12, spaceAfter=6
    )
    body = ParagraphStyle('Body', parent=styles['Normal'], fontSize=10, leading=14)
    
    story = []
    
    story.append(Paragraph("GENESIS ACADEMY", title_style))
    story.append(Paragraph("Student Performance Report Card", subtitle))
    story.append(Paragraph(f"Generated on: {datetime.now().strftime('%d %B %Y')}", subtitle))
    story.append(Spacer(1, 8))
    
    info_data = [
        ["Student Name", student_row['name'], "Class / Section", f"{student_row['class']} - {student_row['section']}"],
        ["Roll No", student_row['roll_no'], "Batch", student_row['batch'] or "-"],
        ["Parent", student_row['parent_name'] or "-", "Contact", student_row['parent_phone'] or "-"]
    ]
    info_table = Table(info_data, colWidths=[30*mm, 55*mm, 35*mm, 50*mm])
    info_table.setStyle(TableStyle([
        ('BACKGROUND', (0, 0), (0, -1), HexColor("#edf2f7")),
        ('BACKGROUND', (2, 0), (2, -1), HexColor("#edf2f7")),
        ('FONTNAME', (0, 0), (-1, -1), 'Helvetica'),
        ('FONTSIZE', (0, 0), (-1, -1), 9),
        ('GRID', (0, 0), (-1, -1), 0.5, colors.grey),
        ('VALIGN', (0, 0), (-1, -1), 'MIDDLE'),
        ('LEFTPADDING', (0, 0), (-1, -1), 6),
        ('RIGHTPADDING', (0, 0), (-1, -1), 6),
        ('TOPPADDING', (0, 0), (-1, -1), 5),
        ('BOTTOMPADDING', (0, 0), (-1, -1), 5),
    ]))
    story.append(info_table)
    story.append(Spacer(1, 12))
    
    story.append(Paragraph("Recent Examination Results", heading))
    if not sheets_df.empty:
        exam_data = [["Exam", "Subject", "Score", "Max", "%", "Date"]]
        for _, r in sheets_df.head(8).iterrows():
            pct = (r['score'] / r['max_marks'] * 100) if r['max_marks'] else 0
            exam_data.append([
                str(r.get('exam_name', ''))[:25],
                str(r.get('subject', '')),
                f"{r['score']:.1f}",
                f"{r['max_marks']:.0f}",
                f"{pct:.0f}%",
                str(r.get('evaluated_at', ''))[:10]
            ])
        exam_table = Table(exam_data, colWidths=[55*mm, 30*mm, 20*mm, 18*mm, 18*mm, 30*mm])
        exam_table.setStyle(TableStyle([
            ('BACKGROUND', (0, 0), (-1, 0), HexColor("#2c5282")),
            ('TEXTCOLOR', (0, 0), (-1, 0), colors.white),
            ('FONTNAME', (0, 0), (-1, 0), 'Helvetica-Bold'),
            ('FONTSIZE', (0, 0), (-1, -1), 8),
            ('GRID', (0, 0), (-1, -1), 0.4, colors.grey),
            ('ALIGN', (2, 0), (4, -1), 'CENTER'),
            ('VALIGN', (0, 0), (-1, -1), 'MIDDLE'),
            ('TOPPADDING', (0, 0), (-1, -1), 4),
            ('BOTTOMPADDING', (0, 0), (-1, -1), 4),
            ('ROWBACKGROUNDS', (0, 1), (-1, -1), [colors.white, HexColor("#f7fafc")]),
        ]))
        story.append(exam_table)
    else:
        story.append(Paragraph("No evaluations recorded yet.", body))
    
    story.append(Paragraph("Performance Summary (Subject-wise)", heading))
    if not sheets_df.empty:
        summary = sheets_df.groupby('subject').agg(
            attempts=('score', 'count'),
            avg_score=('score', 'mean'),
            max_possible=('max_marks', 'mean')
        ).reset_index()
        summary['pct'] = (summary['avg_score'] / summary['max_possible'] * 100).round(1)
        
        sum_data = [["Subject", "Attempts", "Avg Score", "Avg %"]]
        for _, r in summary.iterrows():
            sum_data.append([r['subject'], str(int(r['attempts'])), f"{r['avg_score']:.1f}", f"{r['pct']:.0f}%"])
        
        sum_table = Table(sum_data, colWidths=[50*mm, 30*mm, 35*mm, 30*mm])
        sum_table.setStyle(TableStyle([
            ('BACKGROUND', (0, 0), (-1, 0), HexColor("#38a169")),
            ('TEXTCOLOR', (0, 0), (-1, 0), colors.white),
            ('FONTNAME', (0, 0), (-1, 0), 'Helvetica-Bold'),
            ('FONTSIZE', (0, 0), (-1, -1), 9),
            ('GRID', (0, 0), (-1, -1), 0.4, colors.grey),
            ('ALIGN', (1, 0), (-1, -1), 'CENTER'),
            ('TOPPADDING', (0, 0), (-1, -1), 4),
            ('BOTTOMPADDING', (0, 0), (-1, -1), 4),
        ]))
        story.append(sum_table)
    
    if not sheets_df.empty:
        latest = sheets_df.iloc[0]
        story.append(Paragraph("Latest Feedback & Suggestions", heading))
        fb = (latest.get('feedback') or "")[:600]
        story.append(Paragraph(fb.replace("\n", "<br/>"), body))
        story.append(Spacer(1, 6))
        sug = (latest.get('suggestions') or "")[:400]
        story.append(Paragraph(f"<b>Suggestions:</b><br/>{sug.replace(chr(10), '<br/>')}", body))
        story.append(Spacer(1, 6))
        prac = (latest.get('practice_problems') or "")[:400]
        story.append(Paragraph(f"<b>Recommended Practice:</b><br/>{prac.replace(chr(10), '<br/>')}", body))
    
    story.append(Spacer(1, 20))
    story.append(Paragraph(
        "This is a computer-generated report from Genesis Academy Performance System. "
        "For any clarification contact the class teacher. Keep practising!",
        ParagraphStyle('Footer', parent=styles['Normal'], fontSize=8, textColor=colors.grey, alignment=TA_CENTER)
    ))
    
    doc.build(story)
    return output_path

# ==================== WHATSAPP HELPERS ====================
def send_whatsapp_twilio(to_number, message):
    if not (TWILIO_ACCOUNT_SID and TWILIO_AUTH_TOKEN):
        return False, "Twilio credentials not set. Set TWILIO_ACCOUNT_SID and TWILIO_AUTH_TOKEN env vars."
    
    try:
        from twilio.rest import Client
        client = Client(TWILIO_ACCOUNT_SID, TWILIO_AUTH_TOKEN)
        
        if not to_number.startswith("whatsapp:"):
            to_number = f"whatsapp:+91{to_number[-10:]}" if len(to_number) >= 10 else f"whatsapp:{to_number}"
        
        msg = client.messages.create(
            body=message,
            from_=TWILIO_WHATSAPP_FROM,
            to=to_number
        )
        return True, msg.sid
    except Exception as e:
        return False, str(e)

def build_parent_message(student_name, exam_name, subject, score, max_marks, feedback_snippet, suggestions_snippet):
    return f"""Dear Parent,

*Genesis Academy* – Performance Update

Student: *{student_name}*
Exam: {exam_name} ({subject})
Score: *{score}/{max_marks}*

Feedback:
{(feedback_snippet or '')[:280]}...

Suggestions:
{(suggestions_snippet or '')[:180]}

Please encourage regular practice of the recommended problems.

Regards,
Genesis Academy
(This is an automated message)"""

# ==================== DATA HELPERS ====================
def get_students():
    conn = get_conn()
    df = pd.read_sql_query("SELECT * FROM students ORDER BY class, section, roll_no", conn)
    conn.close()
    return df

def get_exams():
    conn = get_conn()
    df = pd.read_sql_query("SELECT * FROM exams ORDER BY exam_date DESC", conn)
    conn.close()
    return df

def get_answer_sheets(student_id=None, exam_id=None):
    conn = get_conn()
    query = """
    SELECT a.*, s.name as student_name, s.class, s.section, s.roll_no, s.batch,
           e.name as exam_name, e.subject
    FROM answer_sheets a
    JOIN students s ON a.student_id = s.id
    JOIN exams e ON a.exam_id = e.id
    WHERE 1=1
    """
    params = []
    if student_id:
        query += " AND a.student_id = ?"
        params.append(student_id)
    if exam_id:
        query += " AND a.exam_id = ?"
        params.append(exam_id)
    query += " ORDER BY a.evaluated_at DESC"
    df = pd.read_sql_query(query, conn, params=params)
    conn.close()
    return df

def log_performance(student_id, subject, period_type, avg_score, remarks):
    conn = get_conn()
    today = datetime.now().date()
    if period_type == "weekly":
        start = today - timedelta(days=today.weekday())
        end = start + timedelta(days=6)
    elif period_type == "fortnight":
        start = today - timedelta(days=14)
        end = today
    else:
        start = today.replace(day=1)
        end = (start + timedelta(days=32)).replace(day=1) - timedelta(days=1)
    
    conn.execute(
        "INSERT INTO performance_logs (student_id, subject, period_type, period_start, period_end, average_score, remarks) VALUES (?,?,?,?,?,?,?)",
        (student_id, subject, period_type, str(start), str(end), avg_score, remarks)
    )
    conn.commit()
    conn.close()

# ==================== UI ====================
st.title("🎓 Genesis Academy")
st.markdown("### Student Result & Performance Tracking System — **v2.0 Enhanced**")
st.caption("AI Grading (OCR + CBSE Rubric + optional LLM) • Teacher Override • Bulk Eval • PDF Report Cards • WhatsApp Ready • Timetables • Full Tracking")

with st.sidebar:
    st.markdown("### Navigation")
    menu = st.radio(
        "Go to",
        [
            "🏠 Dashboard",
            "👨‍🎓 Students",
            "📝 Exams & Syllabus",
            "📸 AI Evaluation (Single + Bulk)",
            "✏️ Teacher Override",
            "📊 Performance Reports",
            "📄 PDF Report Cards",
            "📅 Timetable Generator",
            "📱 Parent WhatsApp",
            "⚙️ Settings & Integrations"
        ],
        label_visibility="collapsed"
    )
    st.markdown("---")
    st.info("v2.0 • All production upgrades included")

if menu == "🏠 Dashboard":
    st.header("Dashboard")
    students_df = get_students()
    exams_df = get_exams()
    sheets_df = get_answer_sheets()
    
    c1, c2, c3, c4 = st.columns(4)
    c1.metric("Students", len(students_df))
    c2.metric("Exams", len(exams_df))
    c3.metric("Evaluated Sheets", len(sheets_df[sheets_df['status']=='evaluated']) if not sheets_df.empty else 0)
    c4.metric("Overrides", int(sheets_df['teacher_override'].sum()) if not sheets_df.empty and 'teacher_override' in sheets_df.columns else 0)
    
    st.subheader("Recent Evaluations")
    if not sheets_df.empty:
        display_cols = ['student_name', 'exam_name', 'subject', 'score', 'max_marks', 'status', 'teacher_override', 'evaluated_at']
        st.dataframe(sheets_df[[c for c in display_cols if c in sheets_df.columns]].head(12), use_container_width=True)
    else:
        st.info("No evaluations yet. Start with AI Evaluation.")

elif menu == "👨‍🎓 Students":
    st.header("Student Management")
    tab1, tab2 = st.tabs(["View / Export", "Add Student"])
    
    with tab1:
        df = get_students()
        st.dataframe(df, use_container_width=True)
        if not df.empty:
            st.download_button("Download CSV", df.to_csv(index=False), "students.csv", "text/csv")
    
    with tab2:
        with st.form("add_student"):
            name = st.text_input("Student Name*")
            c1, c2, c3 = st.columns(3)
            class_ = c1.text_input("Class*", "10")
            section = c2.text_input("Section*", "A")
            roll = c3.text_input("Roll No*")
            parent_name = st.text_input("Parent Name")
            p1, p2 = st.columns(2)
            phone = p1.text_input("Parent Phone")
            whatsapp = p2.text_input("Parent WhatsApp")
            batch = st.selectbox("Batch", ["Batch-A", "Batch-B", "Batch-C", "Individual"])
            if st.form_submit_button("Add Student", type="primary"):
                if name and class_ and roll:
                    conn = get_conn()
                    conn.execute(
                        "INSERT INTO students (name, class, section, roll_no, parent_name, parent_phone, parent_whatsapp, batch) VALUES (?,?,?,?,?,?,?,?)",
                        (name, class_, section, roll, parent_name, phone, whatsapp or phone, batch)
                    )
                    conn.commit()
                    conn.close()
                    st.success(f"Added {name}")
                    st.rerun()
                else:
                    st.error("Name, Class, Roll No required")

elif menu == "📝 Exams & Syllabus":
    st.header("Exams, Syllabus & Rubrics")
    tab1, tab2 = st.tabs(["Existing Exams", "Create Exam"])
    
    with tab1:
        exams = get_exams()
        st.dataframe(exams[['id', 'name', 'subject', 'class', 'exam_date', 'max_marks']], use_container_width=True)
        if not exams.empty:
            sel = st.selectbox("View full details", exams['name'].tolist())
            ex = exams[exams['name']==sel].iloc[0]
            st.markdown(f"**Syllabus**\n\n{ex['syllabus_text']}")
            st.markdown(f"**Model Answer / Key Points**\n\n{ex['model_answer']}")
            if ex['rubric_json']:
                st.json(json.loads(ex['rubric_json']))
    
    with tab2:
        with st.form("create_exam"):
            name = st.text_input("Exam Name*", "Unit Test 2")
            c1, c2, c3 = st.columns(3)
            subject = c1.selectbox("Subject", ["Mathematics", "Science", "English", "Social Science", "Hindi"])
            class_ = c2.text_input("Class", "10")
            exam_date = c3.date_input("Exam Date")
            max_marks = st.number_input("Max Marks", 5.0, 100.0, 20.0)
            syllabus = st.text_area("Syllabus / Topics*", height=90)
            model = st.text_area("Model Answer / Marking Key Points*", height=120)
            rubric_text = st.text_area("Rubric JSON", value=json.dumps({
                "questions": [
                    {"qno": "1", "max": 5, "keywords": ["key1", "key2"], "type": "descriptive", "bloom": "Understand"},
                    {"qno": "2", "max": 5, "keywords": ["formula", "steps"], "type": "numerical", "bloom": "Apply"}
                ],
                "liberal_marking": True,
                "cbse_notes": "Partial marks for correct method. Keywords & steps important."
            }, indent=2), height=180)
            if st.form_submit_button("Create Exam", type="primary"):
                try:
                    json.loads(rubric_text)
                    conn = get_conn()
                    conn.execute(
                        "INSERT INTO exams (name, subject, class, exam_date, max_marks, syllabus_text, model_answer, rubric_json) VALUES (?,?,?,?,?,?,?,?)",
                        (name, subject, class_, str(exam_date), max_marks, syllabus, model, rubric_text)
                    )
                    conn.commit()
                    conn.close()
                    st.success("Exam created")
                    st.rerun()
                except Exception as e:
                    st.error(str(e))

elif menu == "📸 AI Evaluation (Single + Bulk)":
    st.header("AI-Powered Answer Sheet Evaluation")
    st.markdown("""
**CBSE-aligned liberal marking** • OCR • Rubric engine • **True Multimodal LLM (vision)**  
When you enable “Use real LLM” and provide an OpenAI key, the **actual photos** of the answer sheets are sent to **gpt-4o** (vision model) together with the rubric and model answer for high-accuracy evaluation.  
Supports **single** and **bulk** evaluation.
""")
    
    students = get_students()
    exams = get_exams()
    
    if students.empty or exams.empty:
        st.warning("Add students and create at least one exam first.")
    else:
        mode = st.radio("Mode", ["Single Student", "Bulk (Multiple Students)"], horizontal=True)
        
        use_llm = st.checkbox("Use True Multimodal LLM (gpt-4o or xAI Grok vision) – sends the actual photos", value=False)
        api_key = None
        if use_llm:
            api_key = st.text_input("API Key (OpenAI or xAI Grok)", type="password", value=OPENAI_API_KEY or XAI_API_KEY or "")
            st.caption("Paste OpenAI key (gpt-4o) or xAI key starting with xai- (Grok vision). Auto-detected. Without key → local OCR+rubric engine.")
        
        if mode == "Single Student":
            c1, c2 = st.columns(2)
            student_name = c1.selectbox("Student", students['name'].tolist())
            exam_name = c2.selectbox("Exam", exams['name'].tolist())
            student_id = int(students[students['name']==student_name]['id'].iloc[0])
            exam_row = exams[exams['name']==exam_name].iloc[0]
            exam_id = int(exam_row['id'])
            max_marks = float(exam_row['max_marks'])
            
            uploaded = st.file_uploader("Upload answer sheet photo(s)", type=["jpg","jpeg","png"], accept_multiple_files=True)
            
            if uploaded and st.button("🚀 Evaluate", type="primary"):
                with st.spinner("OCR + Multimodal Evaluation running..."):
                    all_text, paths, img_bytes_list = [], [], []
                    for i, f in enumerate(uploaded):
                        data = f.read()
                        img_bytes_list.append(data)
                        fname = f"s{student_id}_e{exam_id}_{datetime.now().strftime('%Y%m%d%H%M%S')}_{i}.jpg"
                        p = UPLOAD_DIR / fname
                        p.write_bytes(data)
                        paths.append(str(p))
                        all_text.append(f"--- Page {i+1} ---\n{perform_ocr(data)}")
                    full_ocr = "\n\n".join(all_text)
                    
                    result = evaluate_with_rubric(
                        full_ocr, exam_row['rubric_json'], exam_row['model_answer'], max_marks,
                        use_llm=use_llm, api_key=api_key, image_bytes_list=img_bytes_list
                    )
                    
                    conn = get_conn()
                    conn.execute("""
                        INSERT INTO answer_sheets 
                        (student_id, exam_id, image_path, ocr_text, score, max_marks, feedback, suggestions, practice_problems, status, original_ai_score, evaluated_at)
                        VALUES (?,?,?,?,?,?,?,?,?,'evaluated',?,?)
                    """, (student_id, exam_id, json.dumps(paths), full_ocr, result['score'], max_marks,
                          result['feedback'], result['suggestions'], result['practice_problems'], result['score'], datetime.now().isoformat()))
                    conn.commit()
                    conn.close()
                    log_performance(student_id, exam_row['subject'], "weekly", result['score'], f"Auto: {exam_name}")
                    
                    st.success(f"✅ Score: **{result['score']}/{max_marks}**  (Source: {result.get('source','Local')})")
                    st.text_area("OCR Text", full_ocr, height=150)
                    st.markdown(result['feedback'])
                    st.markdown("**Suggestions**")
                    st.markdown(result['suggestions'])
                    st.markdown("**Practice Problems**")
                    st.markdown(result['practice_problems'])
                    for p in paths:
                        try: st.image(p, width=380)
                        except: pass
        
        else:
            st.subheader("Bulk Evaluation")
            exam_name = st.selectbox("Select Exam for bulk", exams['name'].tolist(), key="bulk_exam")
            exam_row = exams[exams['name']==exam_name].iloc[0]
            exam_id = int(exam_row['id'])
            max_marks = float(exam_row['max_marks'])
            
            st.markdown("Upload files. Select students; files are distributed in order.")
            bulk_files = st.file_uploader("Upload multiple answer sheets", type=["jpg","jpeg","png"], accept_multiple_files=True, key="bulk")
            
            selected_students = st.multiselect("Students to evaluate", students['name'].tolist())
            
            if bulk_files and selected_students and st.button("🚀 Run Bulk Evaluation", type="primary"):
                results_summary = []
                files_per_student = max(1, len(bulk_files) // len(selected_students))
                
                with st.spinner(f"Evaluating {len(selected_students)} students..."):
                    file_idx = 0
                    for sname in selected_students:
                        sid = int(students[students['name']==sname]['id'].iloc[0])
                        student_files = bulk_files[file_idx:file_idx+files_per_student]
                        file_idx += files_per_student
                        if not student_files:
                            continue
                        
                        all_text, paths, img_bytes_list = [], [], []
                        for i, f in enumerate(student_files):
                            data = f.read()
                            img_bytes_list.append(data)
                            fname = f"bulk_s{sid}_e{exam_id}_{datetime.now().strftime('%H%M%S')}_{i}.jpg"
                            p = UPLOAD_DIR / fname
                            p.write_bytes(data)
                            paths.append(str(p))
                            all_text.append(perform_ocr(data))
                        full_ocr = "\n\n".join(all_text)
                        
                        result = evaluate_with_rubric(
                            full_ocr, exam_row['rubric_json'], exam_row['model_answer'], max_marks,
                            use_llm=use_llm, api_key=api_key, image_bytes_list=img_bytes_list
                        )
                        
                        conn = get_conn()
                        conn.execute("""
                            INSERT INTO answer_sheets 
                            (student_id, exam_id, image_path, ocr_text, score, max_marks, feedback, suggestions, practice_problems, status, original_ai_score, evaluated_at)
                            VALUES (?,?,?,?,?,?,?,?,?,'evaluated',?,?)
                        """, (sid, exam_id, json.dumps(paths), full_ocr, result['score'], max_marks,
                              result['feedback'], result['suggestions'], result['practice_problems'], result['score'], datetime.now().isoformat()))
                        conn.commit()
                        conn.close()
                        log_performance(sid, exam_row['subject'], "weekly", result['score'], f"Bulk: {exam_name}")
                        results_summary.append({"Student": sname, "Score": result['score'], "Max": max_marks})
                
                st.success("Bulk evaluation complete")
                st.dataframe(pd.DataFrame(results_summary), use_container_width=True)

elif menu == "✏️ Teacher Override":
    st.header("Teacher Score Override & Review")
    st.markdown("Review AI scores and adjust if needed. Original AI score is preserved.")
    
    sheets = get_answer_sheets()
    if sheets.empty:
        st.info("No evaluated sheets yet.")
    else:
        c1, c2 = st.columns(2)
        student_filter = c1.selectbox("Filter by student", ["All"] + sorted(sheets['student_name'].unique().tolist()))
        if student_filter != "All":
            sheets = sheets[sheets['student_name'] == student_filter]
        
        for idx, row in sheets.iterrows():
            with st.expander(f"{row['student_name']} | {row['exam_name']} | AI: {row['score']}/{row['max_marks']} | Override: {bool(row.get('teacher_override'))}"):
                st.markdown(row['feedback'] or "")
                new_score = st.number_input(
                    f"New Score (max {row['max_marks']})", 
                    min_value=0.0, 
                    max_value=float(row['max_marks']), 
                    value=float(row['score']),
                    key=f"score_{row['id']}"
                )
                new_feedback = st.text_area("Adjusted Feedback", value=row['feedback'] or "", key=f"fb_{row['id']}", height=120)
                new_sugg = st.text_area("Adjusted Suggestions", value=row['suggestions'] or "", key=f"sg_{row['id']}", height=80)
                
                if st.button("Save Override", key=f"save_{row['id']}"):
                    conn = get_conn()
                    conn.execute("""
                        UPDATE answer_sheets 
                        SET score=?, feedback=?, suggestions=?, teacher_override=1
                        WHERE id=?
                    """, (new_score, new_feedback, new_sugg, int(row['id'])))
                    conn.commit()
                    conn.close()
                    st.success("Override saved. Original AI score preserved.")
                    st.rerun()

elif menu == "📊 Performance Reports":
    st.header("Performance Tracking")
    students = get_students()
    student_name = st.selectbox("Student", ["All"] + students['name'].tolist())
    period = st.radio("Period", ["weekly", "fortnight", "monthly"], horizontal=True)
    
    conn = get_conn()
    if student_name == "All":
        logs = pd.read_sql_query("""
            SELECT p.*, s.name as student_name FROM performance_logs p 
            JOIN students s ON p.student_id = s.id WHERE p.period_type=? ORDER BY p.created_at DESC
        """, conn, params=[period])
    else:
        sid = int(students[students['name']==student_name]['id'].iloc[0])
        logs = pd.read_sql_query("""
            SELECT p.*, s.name as student_name FROM performance_logs p 
            JOIN students s ON p.student_id = s.id WHERE p.student_id=? AND p.period_type=? ORDER BY p.created_at DESC
        """, conn, params=[sid, period])
    conn.close()
    
    if not logs.empty:
        st.dataframe(logs[['student_name','subject','period_start','period_end','average_score','remarks']], use_container_width=True)
        if student_name != "All":
            st.line_chart(logs.set_index('period_start')['average_score'])
    else:
        st.info("No logs yet. Evaluate sheets to auto-populate.")
    
    st.subheader("Subject-wise from Answer Sheets")
    sheets = get_answer_sheets()
    if not sheets.empty:
        if student_name != "All":
            sheets = sheets[sheets['student_name']==student_name]
        summary = sheets.groupby(['student_name','subject']).agg(avg_score=('score','mean'), max_m=('max_marks','first')).reset_index()
        summary['pct'] = (summary['avg_score']/summary['max_m']*100).round(1)
        st.dataframe(summary, use_container_width=True)

elif menu == "📄 PDF Report Cards":
    st.header("Generate PDF Report Cards")
    students = get_students()
    if students.empty:
        st.warning("No students.")
    else:
        sel_students = st.multiselect("Select students", students['name'].tolist(), default=students['name'].tolist()[:2])
        
        if st.button("Generate PDF Report Cards", type="primary"):
            generated = []
            for sname in sel_students:
                srow = students[students['name']==sname].iloc[0]
                sid = int(srow['id'])
                sheets = get_answer_sheets(student_id=sid)
                conn = get_conn()
                perf = pd.read_sql_query("SELECT * FROM performance_logs WHERE student_id=?", conn, params=[sid])
                conn.close()
                
                out_path = REPORTS_DIR / f"ReportCard_{sname.replace(' ','_')}_{datetime.now().strftime('%Y%m%d')}.pdf"
                generate_pdf_report_card(srow, sheets, perf, out_path)
                generated.append(str(out_path))
            
            st.success(f"Generated {len(generated)} report card(s)")
            for p in generated:
                with open(p, "rb") as f:
                    st.download_button(
                        f"Download {Path(p).name}",
                        f,
                        file_name=Path(p).name,
                        mime="application/pdf",
                        key=p
                    )

elif menu == "📅 Timetable Generator":
    st.header("Individual & Batch Timetable")
    tab1, tab2 = st.tabs(["Generate", "Saved"])
    
    with tab1:
        mode = st.radio("Mode", ["Individual", "Batch"], horizontal=True)
        students = get_students()
        if mode == "Individual":
            sel = st.selectbox("Student", students['name'].tolist())
            target = {"type":"student", "id": int(students[students['name']==sel]['id'].iloc[0]), "name": sel}
        else:
            batch = st.selectbox("Batch", students['batch'].dropna().unique().tolist())
            target = {"type":"batch", "name": batch}
        
        subjects = ["Mathematics", "Science", "English", "Social Science", "Hindi", "Revision", "Practice Test", "Doubt Clearing"]
        days = ["Monday","Tuesday","Wednesday","Thursday","Friday","Saturday"]
        schedule = {}
        for day in days:
            with st.expander(day):
                schedule[day] = st.multiselect(f"Slots – {day}", subjects, key=f"tt_{day}")
        
        title = st.text_input("Title", f"Weekly Plan – {target['name']}")
        if st.button("Save Timetable"):
            conn = get_conn()
            sid = target.get("id")
            bname = target['name'] if target['type']=='batch' else None
            conn.execute("INSERT INTO timetables (student_id, batch, title, schedule_json) VALUES (?,?,?,?)",
                         (sid, bname, title, json.dumps(schedule)))
            conn.commit()
            conn.close()
            st.success("Saved")
            for d, slots in schedule.items():
                st.markdown(f"**{d}:** {', '.join(slots) if slots else 'Self study / Free'}")
    
    with tab2:
        conn = get_conn()
        tts = pd.read_sql_query("SELECT * FROM timetables ORDER BY created_at DESC", conn)
        conn.close()
        if not tts.empty:
            for _, r in tts.iterrows():
                with st.expander(r['title']):
                    st.json(json.loads(r['schedule_json']))
        else:
            st.info("None saved yet.")

elif menu == "📱 Parent WhatsApp":
    st.header("Parent Communication via WhatsApp")
    st.info("Ready for Twilio WhatsApp Business API. Set environment variables TWILIO_ACCOUNT_SID, TWILIO_AUTH_TOKEN, TWILIO_WHATSAPP_FROM.")
    
    students = get_students()
    sheets = get_answer_sheets()
    
    if sheets.empty:
        st.warning("No evaluated results to share.")
    else:
        sname = st.selectbox("Student", students['name'].tolist())
        srow = students[students['name']==sname].iloc[0]
        sid = int(srow['id'])
        parent_wa = srow['parent_whatsapp'] or srow['parent_phone']
        
        stud_sheets = sheets[sheets['student_id']==sid]
        if stud_sheets.empty:
            st.info("No results for this student.")
        else:
            latest = stud_sheets.iloc[0]
            msg = build_parent_message(
                sname, latest['exam_name'], latest['subject'],
                latest['score'], latest['max_marks'],
                latest['feedback'], latest['suggestions']
            )
            st.text_area("Message Preview", msg, height=280)
            st.markdown(f"**Target WhatsApp:** `{parent_wa}`")
            
            col1, col2 = st.columns(2)
            if col1.button("📋 Copy Message (Manual Send)"):
                st.code(msg)
                st.success("Copy the message above and send via WhatsApp.")
            
            if col2.button("📤 Send via Twilio API", type="primary"):
                ok, result = send_whatsapp_twilio(parent_wa, msg)
                conn = get_conn()
                conn.execute("INSERT INTO whatsapp_logs (student_id, message, status) VALUES (?,?,?)",
                             (sid, msg, "sent" if ok else f"failed: {result}"))
                if ok:
                    conn.execute("UPDATE performance_logs SET shared_with_parent=1 WHERE student_id=?", (sid,))
                conn.commit()
                conn.close()
                if ok:
                    st.success(f"Sent! SID: {result}")
                else:
                    st.error(f"Failed: {result}")
                    st.info("Without credentials the message is still logged. Use Copy for manual send.")

elif menu == "⚙️ Settings & Integrations":
    st.header("Settings, Integrations & Mobile Roadmap")
    
    st.subheader("1. LLM Integration (Stronger AI Grading)")
    st.markdown("""
    - Local CBSE rubric engine is always available (no key needed).
    - For production accuracy: set `OPENAI_API_KEY` or `XAI_API_KEY` (Grok).
    - In the Evaluation page, tick **Use real LLM**.
    - Recommended models: `gpt-4o` / `gpt-4o-mini` (vision capable) or Grok.
    - For true image understanding, pass the image bytes to a multimodal model (code ready for extension).
    """)
    
    st.subheader("2. WhatsApp / Twilio")
    st.code("""
# Set these environment variables:
export TWILIO_ACCOUNT_SID="ACxxxxxxxx"
export TWILIO_AUTH_TOKEN="your_auth_token"
export TWILIO_WHATSAPP_FROM="whatsapp:+14155238886"   # or your approved number

# Then the Send button will deliver real messages.
# WhatsApp Business API Cloud API can also be used with similar HTTP calls.
    """, language="bash")
    
    st.subheader("3. PDF Report Cards")
    st.markdown("Already implemented under **PDF Report Cards** menu. Professional A4 cards with scores, feedback and suggestions.")
    
    st.subheader("4. Teacher Override + Bulk")
    st.markdown("Fully available under **Teacher Override** and **AI Evaluation (Bulk)** tabs.")
    
    st.subheader("5. Mobile App Wrapper Roadmap")
    st.markdown("""
**Recommended approach (production):**
- Keep this Streamlit / FastAPI backend as the core API.
- Build a **Flutter** or **React Native** mobile app that:
  - Uses the same SQLite / REST endpoints
  - Allows teachers to photograph answer sheets and upload
  - Shows parent dashboard with results + WhatsApp deep links
  - Offline-first for timetable and past reports

**Quick PWA option (already possible):**
- Run Streamlit with `--server.enableCORS false` and add a manifest.json + service worker for installable web app on mobile.

**Minimal Flutter skeleton structure** (create separately):
```
lib/
  main.dart
  screens/
    login.dart
    dashboard.dart
    evaluate.dart      # camera + upload
    reports.dart
    timetable.dart
  services/
    api.dart           # talks to this backend
```
I can generate a full Flutter starter project in a follow-up if needed.
    """)
    
    st.subheader("Database & Tools")
    st.code(f"DB: {DB_PATH}\nUploads: {UPLOAD_DIR}\nReports: {REPORTS_DIR}")
    
    if st.button("Clear all answer sheets (demo reset)"):
        conn = get_conn()
        conn.execute("DELETE FROM answer_sheets")
        conn.commit()
        conn.close()
        st.success("Cleared")

st.sidebar.markdown("---")
st.sidebar.caption("Genesis Academy v2.0 • Complete working prototype")
