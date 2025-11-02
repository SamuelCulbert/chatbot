# app.py
from flask import Flask, render_template, request, jsonify, session, redirect, url_for
from imagekitio import ImageKit
import replicate
import base64
import os
import psycopg2
import psycopg2.extras
import psycopg2.errors
import google.generativeai as genai
import requests
app = Flask(__name__)
# Replace with a secure random secret in production (and move to env var)
app.secret_key = "8f50c9fbcc43083224dd25a889d7c1d3"

# Configure Gemini
genai.configure(api_key=os.getenv("GEMINI_API_KEY"))
REPLICATE_API_TOKEN = os.getenv("REPLICATE_API_TOKEN")
imagekit = ImageKit(
    private_key=os.getenv("IMAGEKIT_PRIVATE_KEY"),
    public_key=os.getenv("IMAGEKIT_PUBLIC_KEY"),
    url_endpoint=os.getenv("IMAGEKIT_URL_ENDPOINT")
)

# Database connection string from environment (Neon / Supabase / Koyeb DB)
DB_URL = os.getenv("DATABASE_URL")
if not DB_URL:
    raise RuntimeError("DATABASE_URL environment variable is required")

def get_conn():
    return psycopg2.connect(DB_URL, cursor_factory=psycopg2.extras.DictCursor)

# ----------------- Initialize DB (creates tables if missing) ----------------- #
def init_db():
    with get_conn() as conn:
        cur = conn.cursor()
        # users table includes email, birthday, model preference
        cur.execute("""
            CREATE TABLE IF NOT EXISTS users (
                id SERIAL PRIMARY KEY,
                username TEXT UNIQUE NOT NULL,
                password TEXT NOT NULL,
                email TEXT,
                birthday DATE,
                model TEXT DEFAULT 'models/gemini-2.0-flash'
            );
        """)
        cur.execute("""
            CREATE TABLE IF NOT EXISTS chats (
                id SERIAL PRIMARY KEY,
                user_id INTEGER REFERENCES users(id) ON DELETE CASCADE,
                message TEXT,
                reply TEXT,
                created_at TIMESTAMP DEFAULT current_timestamp
            );
        """)
        conn.commit()

init_db()

# ----------------- Page routes ----------------- #
@app.route("/")
def home():
    if "user_id" in session:
        return redirect(url_for("chat_page"))
    return redirect(url_for("login_page"))

@app.route("/login")
def login_page():
    if "user_id" in session:
        return redirect(url_for("chat_page"))
    return render_template("login.html")

@app.route("/signup_page")
def signup_page():
    # new separate signup page
    if "user_id" in session:
        return redirect(url_for("chat_page"))
    return render_template("signup.html")

@app.route("/chat")
def chat_page():
    if "user_id" not in session:
        return redirect(url_for("login_page"))
    return render_template("chat.html")

@app.route("/settings")
def settings_page():
    if "user_id" not in session:
        return redirect(url_for("login_page"))
    with get_conn() as conn:
        cur = conn.cursor()
        cur.execute("SELECT id, username, email, birthday, model FROM users WHERE id=%s;", (session["user_id"],))
        user = cur.fetchone()
        # pass user to template (user can be None if something went wrong)
    return render_template("settings.html", user=user)

@app.route("/logout")
def logout():
    session.pop("user_id", None)
    return redirect(url_for("login_page"))

# ----------------- Auth APIs ----------------- #
@app.route("/signup", methods=["POST"])
def signup():
    """
    Expected JSON: { email, birthday, username, password }
    Returns JSON: { success: True } or { error: "..." }
    On success, sets session user_id.
    """
    data = request.get_json() or {}
    email = data.get("email", "").strip()
    birthday = data.get("birthday", "").strip()  # expect YYYY-MM-DD or empty
    username = data.get("username", "").strip()
    password = data.get("password", "").strip()

    if not username or not password or not email or not birthday:
        return jsonify({"error": "Missing fields"}), 400

    try:
        with get_conn() as conn:
            cur = conn.cursor()
            cur.execute(
                "INSERT INTO users (username, password, email, birthday) VALUES (%s, %s, %s, %s) RETURNING id;",
                (username, password, email, birthday)
            )
            row = cur.fetchone()
            conn.commit()
            user_id = row["id"]
            session["user_id"] = user_id
            return jsonify({"success": True})
    except psycopg2.errors.UniqueViolation:
        # duplicate username
        return jsonify({"error": "Username already exists"}), 400
    except Exception as e:
        # generic error
        return jsonify({"error": str(e)}), 500

@app.route("/login", methods=["POST"])
def login():
    """
    Expected JSON: { username, password }
    Returns JSON: { success: True } or { error: "User not found" / "Invalid password" }
    """
    data = request.get_json() or {}
    username = data.get("username", "").strip()
    password = data.get("password", "").strip()

    if not username or not password:
        return jsonify({"error": "Missing username or password"}), 400

    with get_conn() as conn:
        cur = conn.cursor()
        cur.execute("SELECT id, password FROM users WHERE username=%s;", (username,))
        user = cur.fetchone()
        if not user:
            return jsonify({"error": "User not found"}), 404
        # plain password check (same as original). Replace with hash in production
        if user["password"] != password:
            return jsonify({"error": "Invalid password"}), 401
        # OK
        session["user_id"] = user["id"]
        return jsonify({"success": True})

# ----------------- Chat endpoints ----------------- #
@app.route("/chat_api", methods=["POST"])
def chat_api():
    """
    Send a message to the selected Gemini model for the logged-in user.
    Returns JSON: { reply: "..." } or { error: "..." }
    """
    if "user_id" not in session:
        return jsonify({"error": "Unauthorized"}), 403

    data = request.get_json() or {}
    message = (data.get("message") or "").strip()
    if not message:
        return jsonify({"error": "Empty message"}), 400

    # get user's selected model from DB
    with get_conn() as conn:
        cur = conn.cursor()
        cur.execute("SELECT model FROM users WHERE id=%s;", (session["user_id"],))
        row = cur.fetchone()
        model_name = (row["model"] if row and row["model"] else "models/gemini-2.5-flash")

    try:
        # call Gemini model
        model = genai.GenerativeModel(model_name)
        response = model.generate_content(message)
        reply = response.text.strip()

        # save chat
        with get_conn() as conn:
            cur = conn.cursor()
            cur.execute(
                "INSERT INTO chats (user_id, message, reply) VALUES (%s, %s, %s);",
                (session["user_id"], message, reply)
            )
            conn.commit()

        return jsonify({"reply": reply})
    except Exception as e:
        return jsonify({"error": str(e)}), 500

@app.route("/chats", methods=["GET"])
def get_chats():
    """
    Return user's chats (id, message, reply)
    """
    if "user_id" not in session:
        return jsonify({"error": "Unauthorized"}), 403

    with get_conn() as conn:
        cur = conn.cursor()
        cur.execute("SELECT id, message, reply, created_at FROM chats WHERE user_id=%s ORDER BY created_at ASC;", (session["user_id"],))
        rows = cur.fetchall()
        chats = [{"id": r["id"], "message": r["message"], "reply": r["reply"], "created_at": r["created_at"].isoformat()} for r in rows]
    return jsonify(chats)

@app.route("/delete_chat/<int:chat_id>", methods=["DELETE"])
def delete_chat(chat_id):
    if "user_id" not in session:
        return jsonify({"error": "Unauthorized"}), 403
    with get_conn() as conn:
        cur = conn.cursor()
        cur.execute("DELETE FROM chats WHERE id=%s AND user_id=%s;", (chat_id, session["user_id"]))
        conn.commit()
    return jsonify({"success": True})


@app.route("/upload_image", methods=["POST"])
def upload_image():
    if "user_id" not in session:
        return jsonify({"error": "Unauthorized"}), 403

    file = request.files.get("file")
    if not file:
        return jsonify({"error": "No file uploaded"}), 400

    try:
        content = file.read()
        model = genai.GenerativeModel("models/gemini-2.5-flash")
        result = model.generate_content([
            {"role": "user", "parts": [
                {"text": "Describe this image:"},
                {"inline_data": {"mime_type": file.mimetype, "data": content}}
            ]}
        ])
        reply = result.text.strip() if result and result.text else "No response."

        with get_conn() as conn:
            cur = conn.cursor()
            cur.execute(
                "INSERT INTO chats (user_id, message, reply) VALUES (%s, %s, %s);",
                (session["user_id"], "🖼️ Image uploaded", reply)
            )
            conn.commit()

        return jsonify({"reply": reply})
    except Exception as e:
        return jsonify({"error": str(e)}), 500

@app.route("/generate_image", methods=["POST"])
def generate_image():
    if "user_id" not in session:
        return jsonify({"error": "Unauthorized"}), 403

    data = request.get_json()
    prompt = data.get("prompt", "").strip()
    if not prompt:
        return jsonify({"error": "Prompt required"}), 400

    try:
        headers = {"Authorization": f"Bearer {os.getenv('HUGGINGFACE_API_KEY')}"}
        payload = {"inputs": prompt}
        hf_url = "https://api-inference.huggingface.co/models/prompthero/openjourney-v4"

        response = requests.post(hf_url, headers=headers, json=payload, timeout=120)

        if response.status_code != 200:
            return jsonify({"error": f"Hugging Face error: {response.text}"}), response.status_code

        # Upload to ImageKit
        upload = imagekit.upload(
            file=response.content,
            file_name=f"generated_{session['user_id']}.png"
        )
        image_url = upload.url

        # Save chat entry
        with get_conn() as conn:
            cur = conn.cursor()
            cur.execute(
                "INSERT INTO chats (user_id, message, reply) VALUES (%s, %s, %s);",
                (session["user_id"], f"🖼️ Generated image: {prompt}", image_url)
            )
            conn.commit()

        return jsonify({"image": image_url})

    except Exception as e:
        return jsonify({"error": str(e)}), 500



# ----------------- Settings update API ----------------- #
@app.route("/update_settings", methods=["POST"])
def update_settings():
    """
    Body: { email, birthday, model } - updates user profile and model selection
    """
    if "user_id" not in session:
        return jsonify({"error": "Unauthorized"}), 403

    data = request.get_json() or {}
    email = data.get("email")
    birthday = data.get("birthday")
    model = data.get("model")

    with get_conn() as conn:
        cur = conn.cursor()
        # update only provided fields
        cur.execute("UPDATE users SET email = COALESCE(%s, email), birthday = COALESCE(%s, birthday), model = COALESCE(%s, model) WHERE id = %s;",
                    (email, birthday, model, session["user_id"]))
        conn.commit()

        # return saved record
        cur.execute("SELECT id, username, email, birthday, model FROM users WHERE id=%s;", (session["user_id"],))
        user = cur.fetchone()

    return jsonify({"success": True, "user": {"id": user["id"], "username": user["username"], "email": user["email"], "birthday": (user["birthday"].isoformat() if user["birthday"] else None), "model": user["model"]}})

# ----------------- Utility: list models (optional) ----------------- #
@app.route("/models_list")
def models_list():
    try:
        models = [m.name for m in genai.list_models()]
        return jsonify({"models": models})
    except Exception as e:
        return jsonify({"error": str(e)}), 500

# ----------------- Run ----------------- #
if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.getenv("PORT", 8080)))

















