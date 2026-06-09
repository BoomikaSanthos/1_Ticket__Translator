"""
BACKEND MODULE 1: Language Detection & Translation Service
==========================================================
Handles:
  - Detect language of any incoming ticket text
  - Translate ticket text → English
  - Translate engineer reply → customer's original language
  - Glossary-aware translation (preserves technical terms)

Tech: Python, Groq API (LLaMA 3), Flask
"""

from flask import Flask, request, jsonify
from flask_cors import CORS
import requests
import os

app = Flask(__name__)
CORS(app)  # Allow frontend to call this API

GROQ_API_KEY = os.getenv("GROQ_API_KEY", "YOUR_GROQ_API_KEY_HERE")
GROQ_URL = "https://api.groq.com/openai/v1/chat/completions"
MODEL = "llama3-8b-8192"

IS_MOCK_MODE = (GROQ_API_KEY == "YOUR_GROQ_API_KEY_HERE" or not GROQ_API_KEY)
if IS_MOCK_MODE:
    print("Warning: GROQ_API_KEY not set. Running Translation Service in Mock Mode.")

# Glossary: technical terms that should never be translated
GLOSSARY = {
    "SLA": "Service Level Agreement",
    "OTP": "One-Time Password",
    "VPN": "Virtual Private Network",
    "ETA": "Estimated Time of Arrival",
    "API": "Application Programming Interface",
    "IT":  "Information Technology",
}

# Mock translation datasets for offline / local-testing mode
MOCK_TRANSLATIONS = {
    # Hindi
    "मेरा लैपटॉप बंद हो गया और चालू नहीं हो रहा है।": "My laptop shut down and is not turning on.",
    "मेरा लैपटॉप बंद हो गया और चालू नहीं हो रहा है": "My laptop shut down and is not turning on.",
    "पासवर्ड भूल गया हूँ, कृपया रीसेट करें।": "I forgot my password, please reset it.",
    "पासवर्ड भूल गया हूँ, कृपया रीसेट करें": "I forgot my password, please reset it.",
    # Tamil
    "என் கணினி வேலை செய்யவில்லை.": "My computer is not working.",
    "என் கணினி வேலை செய்யவில்லை": "My computer is not working.",
    # French
    "bonjour, mon ordinateur ne fonctionne pas.": "Hello, my computer is not working.",
    "bonjour, mon ordinateur ne fonctionne pas": "Hello, my computer is not working.",
    # Spanish
    "hola, no puedo acceder a mi correo electrónico.": "Hello, I cannot access my email.",
    "hola, no puedo acceder a mi correo electrónico": "Hello, I cannot access my email.",
}

MOCK_REPLIES = {
    "please restart your laptop and try again.": {
        "Hindi": "कृपया अपने लैपटॉप को रीस्टार्ट करें और फिर से प्रयास करें।",
        "Tamil": "தயவுசெய்து உங்கள் மடிக்கணினியை மறுதொடக்கம் செய்து மீண்டும் முயற்சிக்கவும்.",
        "French": "Veuillez redémarrer votre ordinateur et réessayer.",
        "Spanish": "Por favor, reinicie su computadora e inténtelo de nuevo.",
    },
    "please restart your laptop and try again": {
        "Hindi": "कृपया अपने लैपटॉप को रीस्टार्ट करें और फिर से प्रयास करें।",
        "Tamil": "தயவுசெய்து உங்கள் மடிக்கணினியை மறுதொடக்கம் செய்து மீண்டும் முயற்சிக்கவும்.",
        "French": "Veuillez redémarrer votre ordinateur et réessayer.",
        "Spanish": "Por favor, reinicie su computadora e inténtelo de nuevo.",
    },
    "your password has been reset. please check your email.": {
        "Hindi": "आपका पासवर्ड रीसेट कर दिया गया है। कृपया अपना ईमेल देखें।",
        "Tamil": "உங்கள் கடவுச்சொல் மீட்டமைக்கப்பட்டது. உங்கள் மின்னஞ்சலைச் சரிபார்க்கவும்.",
        "French": "Votre mot de passe a été réinitialisé. Veuillez vérifier vos e-mails.",
        "Spanish": "Su contraseña ha sido restablecida. Por favor revise su correo electrónico.",
    },
    "your password has been reset. please check your email": {
        "Hindi": "आपका पासवर्ड रीसेट कर दिया गया है। कृपया अपना ईमेल देखें।",
        "Tamil": "உங்கள் கடவுச்சொல் மீட்டமைக்கப்பட்டது. உங்கள் மின்னஞ்சலைச் சரிபார்க்கவும்.",
        "French": "Votre mot de passe a été réinitialisé. Veuillez vérifier vos e-mails.",
        "Spanish": "Su contraseña ha sido restablecida. Por favor revise su correo electrónico.",
    }
}

LANG_MAP = {
    'hi': 'Hindi',
    'ta': 'Tamil',
    'fr': 'French',
    'es': 'Spanish',
    'en': 'English',
    'de': 'German',
    'it': 'Italian',
    'pt': 'Portuguese',
    'ru': 'Russian',
    'zh-cn': 'Chinese',
    'ja': 'Japanese',
    'ko': 'Korean',
    'ar': 'Arabic',
}
LANG_MAP_REV = {v.lower(): k for k, v in LANG_MAP.items()}

def mock_detect_language(text: str) -> str:
    try:
        from langdetect import detect
        code = detect(text)
        return LANG_MAP.get(code, code.upper())
    except Exception:
        text_lower = text.lower().strip()
        if any(ord(c) >= 0x0900 and ord(c) <= 0x097F for c in text):
            return "Hindi"
        if any(ord(c) >= 0x0B80 and ord(c) <= 0x0BFF for c in text):
            return "Tamil"
        if any(w in text_lower for w in ["hola", "computadora", "problema", "servidor", "contraseña", "gracias"]):
            return "Spanish"
        if any(w in text_lower for w in ["bonjour", "ordinateur", "panne", "mot de passe", "merci", "clavier"]):
            return "French"
        return "English"

def mock_translate_to_english(text: str, source_lang: str) -> str:
    if "english" in source_lang.lower():
        return text
    try:
        from deep_translator import GoogleTranslator
        source_code = LANG_MAP_REV.get(source_lang.lower(), 'auto')
        translated = GoogleTranslator(source=source_code, target='en').translate(text)
        return translated
    except Exception as e:
        clean_text = text.strip()
        for k, v in MOCK_TRANSLATIONS.items():
            if k in clean_text or clean_text in k:
                return v
        return f"[Translation Error: {e}] {text}"

def mock_translate_reply(reply: str, target_lang: str) -> str:
    if "english" in target_lang.lower():
        return reply
    try:
        from deep_translator import GoogleTranslator
        target_code = LANG_MAP_REV.get(target_lang.lower())
        if not target_code:
            raise Exception(f"Unsupported target language: {target_lang}")
        translated = GoogleTranslator(source='en', target=target_code).translate(reply)
        return translated
    except Exception as e:
        clean_reply = reply.strip().lower()
        for k, lang_map in MOCK_REPLIES.items():
            if k in clean_reply or clean_reply in k:
                return lang_map.get(target_lang, f"[Translation Error: {e}] {reply}")
        return f"[Translation Error: {e}] {reply}"


def call_groq(user_prompt: str, system_prompt: str) -> str:
    """Call Groq LLM API and return text response."""
    headers = {
        "Authorization": f"Bearer {GROQ_API_KEY}",
        "Content-Type": "application/json",
    }
    payload = {
        "model": MODEL,
        "messages": [
            {"role": "system", "content": system_prompt},
            {"role": "user",   "content": user_prompt},
        ],
        "temperature": 0.1,
    }
    resp = requests.post(GROQ_URL, headers=headers, json=payload, timeout=30)
    resp.raise_for_status()
    return resp.json()["choices"][0]["message"]["content"].strip()


# ── ROUTE 1: Detect Language ─────────────────────────────────────────────────
@app.route("/api/detect-language", methods=["POST"])
def detect_language():
    """
    POST /api/detect-language
    Body: { "text": "Bonjour, mon ordinateur ne fonctionne pas..." }
    Returns: { "language": "French", "success": true }
    """
    data = request.get_json()
    if not data or "text" not in data:
        return jsonify({"error": "Missing 'text' field"}), 400

    text = data["text"].strip()
    if not text:
        return jsonify({"error": "Text cannot be empty"}), 400

    system = (
        "You are a language detection expert. "
        "Reply with ONLY the full language name in English "
        "(e.g., French, Tamil, Spanish, Hindi, English). "
        "No punctuation, no explanation, no other text."
    )
    prompt = f"What language is this text written in?\n\n{text}"

    try:
        if IS_MOCK_MODE:
            language = mock_detect_language(text)
        else:
            language = call_groq(prompt, system)
        return jsonify({"language": language, "success": True})
    except Exception as e:
        return jsonify({"error": str(e), "success": False}), 500


# ── ROUTE 2: Translate to English ────────────────────────────────────────────
@app.route("/api/translate-to-english", methods=["POST"])
def translate_to_english():
    """
    POST /api/translate-to-english
    Body: { "text": "...", "source_language": "French" }
    Returns: { "translated": "...", "success": true }
    """
    data = request.get_json()
    if not data or "text" not in data or "source_language" not in data:
        return jsonify({"error": "Missing 'text' or 'source_language'"}), 400

    text = data["text"].strip()
    source_lang = data["source_language"].strip()

    # If already English, return as-is
    if "english" in source_lang.lower():
        return jsonify({"translated": text, "success": True, "skipped": True})

    # Build glossary note for system prompt
    glossary_lines = "\n".join(
        [f"  - Keep '{k}' as-is (it means {v})" for k, v in GLOSSARY.items()]
    )
    system = (
        "You are a professional IT support ticket translator. "
        "Translate accurately while preserving technical meaning. "
        f"Glossary rules (never translate these terms):\n{glossary_lines}\n"
        "Return ONLY the translated text. No preamble, no explanation."
    )
    prompt = f"Translate this {source_lang} text to English:\n\n{text}"

    try:
        if IS_MOCK_MODE:
            translated = mock_translate_to_english(text, source_lang)
        else:
            translated = call_groq(prompt, system)
        return jsonify({"translated": translated, "success": True})
    except Exception as e:
        return jsonify({"error": str(e), "success": False}), 500


# ── ROUTE 3: Translate Reply Back to Customer ─────────────────────────────────
@app.route("/api/translate-reply", methods=["POST"])
def translate_reply():
    """
    POST /api/translate-reply
    Body: { "reply": "Please restart your laptop...", "target_language": "Tamil" }
    Returns: { "translated_reply": "...", "success": true }
    """
    data = request.get_json()
    if not data or "reply" not in data or "target_language" not in data:
        return jsonify({"error": "Missing 'reply' or 'target_language'"}), 400

    reply = data["reply"].strip()
    target_lang = data["target_language"].strip()

    if "english" in target_lang.lower():
        return jsonify({"translated_reply": reply, "success": True, "skipped": True})

    system = (
        "You are a professional IT support translator. "
        "Translate the engineer's reply into the customer's language. "
        "Use polite, clear, and professional language. "
        "Return ONLY the translated text."
    )
    prompt = f"Translate this English reply to {target_lang}:\n\n{reply}"

    try:
        if IS_MOCK_MODE:
            translated = mock_translate_reply(reply, target_lang)
        else:
            translated = call_groq(prompt, system)
        return jsonify({"translated_reply": translated, "success": True})
    except Exception as e:
        return jsonify({"error": str(e), "success": False}), 500


# ── ROUTE 4: Combined - Detect + Translate in one call ───────────────────────
@app.route("/api/process-ticket-text", methods=["POST"])
def process_ticket_text():
    """
    POST /api/process-ticket-text
    Body: { "text": "मेरा लैपटॉप बंद हो गया..." }
    Returns: { "language": "Hindi", "translated": "My laptop shut down...", "success": true }
    """
    data = request.get_json()
    if not data or "text" not in data:
        return jsonify({"error": "Missing 'text' field"}), 400

    text = data["text"].strip()

    try:
        if IS_MOCK_MODE:
            language = mock_detect_language(text)
            translated = mock_translate_to_english(text, language)
        else:
            # Step 1: Detect language
            lang_system = "You are a language detection expert. Reply with ONLY the full language name in English. No other text."
            language = call_groq(f"What language is this?\n\n{text}", lang_system)

            # Step 2: Translate if needed
            if "english" in language.lower():
                return jsonify({"language": language, "translated": text, "success": True})

            glossary_lines = "\n".join([f"  - Keep '{k}' as-is" for k in GLOSSARY])
            trans_system = (
                f"You are a professional IT support translator. "
                f"Glossary — never translate these:\n{glossary_lines}\n"
                "Return ONLY the translated text."
            )
            translated = call_groq(f"Translate this {language} text to English:\n\n{text}", trans_system)

        return jsonify({"language": language, "translated": translated, "success": True})

    except Exception as e:
        return jsonify({"error": str(e), "success": False}), 500


# ── Health check ──────────────────────────────────────────────────────────────
@app.route("/api/health", methods=["GET"])
def health():
    return jsonify({"status": "ok", "module": "translator", "model": MODEL})


if __name__ == "__main__":
    print("Module 1 - Translation Service running on http://localhost:5001")
    app.run(port=5001, debug=True)