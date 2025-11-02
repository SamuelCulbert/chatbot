from flask import Flask, render_template, request, jsonify, session, redirect
import os, psycopg2, psycopg2.extras, google.generativeai as genai

app = Flask(__name__)
app.secret_key = "8f50c9fbcc43083224dd25a889d7c1d3"
genai.configure(api_key=os.getenv("GEMINI_API_KEY"))

DB_URL = os.getenv("DATABASE_URL")

def get_conn():
    return psycopg2.connect(DB_URL, cursor_factory=psycopg2.extras.DictCursor)

# ---------- INIT DB ---------- #
def init_db():
    with get_conn() as conn:
        cur = conn.cursor()
        cur.execute("""
            CREATE TABLE IF NOT EXISTS users (
                id SERIAL PRIMARY KEY,
                username TEXT UNIQUE NOT NULL,
                password TEXT NOT NULL
            );
        """)
        cur.execute("""
            CREATE TABLE IF NOT EXISTS chats (
                id SERIAL PRIMARY KEY,
                user_id INTEGER REFERENCES users(id),
                message TEXT,
                reply TEXT
            );
        """)
        conn.commit()
init_db()

@app.route("/")
def home():
    if "user_id" in session:
        return redirect("/chat")
    return redirect("/login")

@app.route("/login")
def login_page():
    if "user_id" in session:
        return redirect("/chat")
    return render_template("login.html")

@app.route("/chat")
def chat_page():
    if "user_id" not in session:
        return redirect("/login")
    return render_template("chat.html")

@app.route("/logout")
def logout():
    session.pop("user_id", None)
    return redirect("/login")

@app.route("/signup", methods=["POST"])
def signup():
    data = request.get_json()
    username = data.get("username", "").strip()
    password = data.get("password", "").strip()

    if not username or not password:
        return jsonify({"error": "Missing username or password"}), 400

    try:
        with get_conn() as conn:
            cur = conn.cursor()
            cur.execute("INSERT INTO users (username, password) VALUES (%s, %s) RETURNING id;", (username, password))
            user_id = cur.fetchone()["id"]
            conn.commit()
            session["user_id"] = user_id
            return jsonify({"success": True})
    except psycopg2.errors.UniqueViolation:
        return jsonify({"error": "Username already exists"}), 400

@app.route("/login", methods=["POST"])
def login():
    data = request.get_json()
    username = data.get("username", "").strip()
    password = data.get("password", "").strip()

    with get_conn() as conn:
        cur = conn.cursor()
        cur.execute("SELECT id FROM users WHERE username=%s AND password=%s;", (username, password))
        user = cur.fetchone()
        if not user:
            cur.execute("SELECT id FROM users WHERE username=%s;", (username,))
            if not cur.fetchone():
                return jsonify({"error": "User not found"}), 404
            return jsonify({"error": "Invalid password"}), 401

        session["user_id"] = user["id"]
        return jsonify({"success": True})

@app.route("/chat_api", methods=["POST"])
def chat_api():
    if "user_id" not in session:
        return jsonify({"error": "Unauthorized"}), 403

    data = request.get_json()
    message = data.get("message", "").strip()
    if not message:
        return jsonify({"error": "Empty message"}), 400

    try:
        model = genai.GenerativeModel("models/gemini-2.0-flash")
        response = model.generate_content(message)
        reply = response.text.strip()

        with get_conn() as conn:
            cur = conn.cursor()
            cur.execute("INSERT INTO chats (user_id, message, reply) VALUES (%s, %s, %s);", (session["user_id"], message, reply))
            conn.commit()

        return jsonify({"reply": reply})
    except Exception as e:
        return jsonify({"error": str(e)}), 500

@app.route("/chats", methods=["GET"])
def get_chats():
    if "user_id" not in session:
        return jsonify({"error": "Unauthorized"}), 403

    with get_conn() as conn:
        cur = conn.cursor()
        cur.execute("SELECT id, message, reply FROM chats WHERE user_id=%s;", (session["user_id"],))
        chats = [{"id": row["id"], "message": row["message"], "reply": row["reply"]} for row in cur.fetchall()]
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

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.getenv("PORT", 8080)))
