
import os
import json
import requests
from flask import Flask, request, jsonify
from flask_cors import CORS
from werkzeug.utils import secure_filename

app = Flask(__name__)

BOT_TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN")
CHAT_ID = os.environ.get("TELEGRAM_CHAT_ID")

CORS(app, resources={
    r"/submit": {
        "origins": [
            "https://join-djembo.com",
            "https://www.join-djembo.com",
            "https://evamyself123-art.github.io"
        ]
    }
})

app.config["MAX_CONTENT_LENGTH"] = 45 * 1024 * 1024

ALLOWED_TYPES = {
    "image/jpeg",
    "image/png",
    "image/webp"
}

@app.get("/")
def home():
    return jsonify({"status": "DJEMBO server running"})

@app.post("/submit")
def submit():
    if not BOT_TOKEN or not CHAT_ID:
        return jsonify({"error": "Server not configured"}), 503

    try:
        answers_raw = request.form.get("answers", "{}")
        answers = json.loads(answers_raw)

        if not isinstance(answers, dict):
            return jsonify({"error": "Invalid answers"}), 400

        photos = request.files.getlist("photos")

        if len(photos) > 10:
            return jsonify({"error": "Too many photos"}), 400

        for photo in photos:
            if photo.mimetype not in ALLOWED_TYPES:
                return jsonify({"error": "Invalid file type"}), 400

            if len(photo.read()) > 10 * 1024 * 1024:
                return jsonify({"error": "File too large"}), 400

            photo.seek(0)

        lines = ["Новая анкета DJEMBO", ""]

        for question, answer in answers.items():
            lines.append(str(question))
            lines.append(str(answer))
            lines.append("")

        message = "\n".join(lines)

        for start in range(0, len(message), 3500):
            response = requests.post(
                f"https://api.telegram.org/bot{BOT_TOKEN}/sendMessage",
                data={
                    "chat_id": CHAT_ID,
                    "text": message[start:start + 3500]
                },
                timeout=30
            )
            response.raise_for_status()

        for photo in photos:
            response = requests.post(
                f"https://api.telegram.org/bot{BOT_TOKEN}/sendDocument",
                data={"chat_id": CHAT_ID},
                files={
                    "document": (
                        secure_filename(photo.filename),
                        photo.stream,
                        photo.mimetype
                    )
                },
                timeout=60
            )
            response.raise_for_status()

        return jsonify({"success": True})

    except Exception:
        app.logger.exception("Submission failed")
        return jsonify({"error": "Submission failed"}), 500

@app.errorhandler(413)
def too_large(error):
    return jsonify({"error": "Upload too large"}), 413

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 10000))
    app.run(host="0.0.0.0", port=port)
