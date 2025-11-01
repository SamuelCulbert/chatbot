from flask import Flask, request, jsonify, send_from_directory, session, redirect, url_for, render_template
import google.generativeai as genai
import sqlite3
import os

app = Flask(__name__)
app.secret_key = "8f50c9fbcc43083224dd25a889d7c1d3"

# Configure Gemini API key (must be set in Koyeb Secrets)
genai.configure(api_key=os.getenv("GEMINI_API_KEY"))
DB_name = "database.db"

def init_db():
    with sqlite3.connect(DB_name) as conn:
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

@app.route("/")
def home():
    if "user_id" in session:
        return redirect ("/chat")
    return redirect("/login")

@app.route("/login")
def login_page():
    return render_template("login.html")

@app.route("/chat")
def chat_page():
    if "user_id" not in session:
        return redirect("/login")
    return render_template("chat.html")

@app.route("/signup", methods=["POST"])
def signup():
    data = request.get_json()
    username = data["username"]
    password = data["password"]
    with sqlite3.connect(DB_name) as conn:
        c = conn.cursor()
        try:
            c.execute("INSERT INTO users (username, password) VALUES (?, ?)", (username, password))
            conn.commit()
            return jsonify({"success": True})
        except sqlite3.IntegrityError:
            return jsonify({"error": "Username already exists"}), 400

@app.route("/login", methods=["POST"])
def login():
    data = request.get_json()
    username, password = data["username"], data["password"]
    with sqlite3.connect(DB_NAME) as conn:
        c = conn.cursor()
        c.execute("SELECT id FROM users WHERE username=? AND password=?", (username, password))
        user = c.fetchone()
        if user:
            session["user_id"] = user[0]
            return jsonify({"success": True})
        else:
            return jsonify({"error": "Invalid username or password"}), 401

@app.route("/logout")
def logout():
    session.pop("user_id", None)
    return redirect("/login")
    

# 🌐 Chat endpoint
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

        with sqlite3.connect(DB_name) as conn:
            c = conn.cursor()
            c.execute("INSERT INTO chats (user_id, message, reply) VALUES (?, ?, ?)",
                      (session["user_id"], message, reply))
            conn.commit()

        return jsonify({"reply": reply})
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@app.route("/chats", methods=["GET"])
def get_chats():
    if "user_id" not in session:
        return jsonify({"error": "Unauthorized"}), 403
    with sqlite3.connect(DB_name) as conn:
        c = conn.cursor()
        c.execute("SELECT id, message, reply FROM chats WHERE user_id=?", (session["user_id"],))
        chats = [{"id": row[0], "message": row[1], "reply": row[2]} for row in c.fetchall()]
    return jsonify(chats)


@app.route("/delete_chat/<int:chat_id>", methods=["DELETE"])
def delete_chat(chat_id):
    if "user_id" not in session:
        return jsonify({"error": "Unauthorized"}), 403
    with sqlite3.connect(DB_name) as conn:
        c = conn.cursor()
        c.execute("DELETE FROM chats WHERE id=? AND user_id=?", (chat_id, session["user_id"]))
        conn.commit()
    return jsonify({"success": True})


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.getenv("PORT", 8080)))

