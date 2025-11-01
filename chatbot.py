from flask import Flask, render_template, request, jsonify, session, redirect
import sqlite3
import google.generativeai as genai
import os

app = Flask(__name__)
app.secret_key = "8f50c9fbcc43083224dd25a889d7c1d3"  # keep this secret in production
genai.configure(api_key=os.getenv("GEMINI_API_KEY"))

# ✅ use /tmp for Koyeb compatibility
DB_NAME = "database.db"


# ---------------- DATABASE INIT ---------------- #
def init_db():
    with sqlite3.connect(DB_NAME) as conn:
        c = conn.cursor()
        c.execute("""CREATE TABLE IF NOT EXISTS users (
                        id INTEGER PRIMARY KEY AUTOINCREMENT,
                        username TEXT UNIQUE,
                        password TEXT)""")
        c.execute("""CREATE TABLE IF NOT EXISTS chats (
                        id INTEGER PRIMARY KEY AUTOINCREMENT,
                        user_id INTEGER,
                        message TEXT,
                        reply TEXT,
                        FOREIGN KEY (user_id) REFERENCES users(id))""")
        conn.commit()
init_db()


# ---------------- PAGE ROUTES ---------------- #
@app.route("/")
def home():
    # Auto-redirect logged-in user
    if "user_id" in session:
        return redirect("/chat")
    return redirect("/login")


@app.route("/login")
def login_page():
    # Prevent accessing login if already logged in
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


# ---------------- AUTH APIs ---------------- #
@app.route("/signup", methods=["POST"])
def signup():
    """Create a new account"""
    data = request.get_json()
    username = data.get("username", "").strip()
    password = data.get("password", "").strip()

    if not username or not password:
        return jsonify({"error": "Missing username or password"}), 400

    with sqlite3.connect(DB_NAME) as conn:
        c = conn.cursor()
        try:
            c.execute("INSERT INTO users (username, password) VALUES (?, ?)", (username, password))
            conn.commit()
            user_id = c.lastrowid
            session["user_id"] = user_id
            return jsonify({"success": True})
        except sqlite3.IntegrityError:
            return jsonify({"error": "Username already exists"}), 400


@app.route("/login", methods=["POST"])
def login():
    """Login existing user"""
    data = request.get_json()
    username = data.get("username", "").strip()
    password = data.get("password", "").strip()

    with sqlite3.connect(DB_NAME) as conn:
        c = conn.cursor()
        c.execute("SELECT id FROM users WHERE username=? AND password=?", (username, password))
        user = c.fetchone()

        if not user:
            # Check if username exists
            c.execute("SELECT id FROM users WHERE username=?", (username,))
            exists = c.fetchone()
            if not exists:
                return jsonify({"error": "User not found"}), 404
            else:
                return jsonify({"error": "Invalid password"}), 401

        # success
        session["user_id"] = user[0]
        return jsonify({"success": True})


# ---------------- CHAT ENDPOINTS ---------------- #
@app.route("/chat_api", methods=["POST"])
def chat_api():
    """Send message to Gemini model"""
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

        with sqlite3.connect(DB_NAME) as conn:
            c = conn.cursor()
            c.execute(
                "INSERT INTO chats (user_id, message, reply) VALUES (?, ?, ?)",
                (session["user_id"], message, reply),
            )
            conn.commit()

        return jsonify({"reply": reply})
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@app.route("/chats", methods=["GET"])
def get_chats():
    """Return all chats for logged-in user"""
    if "user_id" not in session:
        return jsonify({"error": "Unauthorized"}), 403
    with sqlite3.connect(DB_NAME) as conn:
        c = conn.cursor()
        c.execute("SELECT id, message, reply FROM chats WHERE user_id=?", (session["user_id"],))
        chats = [{"id": row[0], "message": row[1], "reply": row[2]} for row in c.fetchall()]
    return jsonify(chats)


@app.route("/delete_chat/<int:chat_id>", methods=["DELETE"])
def delete_chat(chat_id):
    """Delete a specific chat"""
    if "user_id" not in session:
        return jsonify({"error": "Unauthorized"}), 403
    with sqlite3.connect(DB_NAME) as conn:
        c = conn.cursor()
        c.execute("DELETE FROM chats WHERE id=? AND user_id=?", (chat_id, session["user_id"]))
        conn.commit()
    return jsonify({"success": True})


# ---------------- MAIN ---------------- #
if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.getenv("PORT", 8080)))
