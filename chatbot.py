from flask import Flask, request, jsonify, send_from_directory
import os
import google.generativeai as genai
app = Flask(__name__)
genai.configure(api_key=os.getenv("GEMINI_API_KEY"))

@app.route("/")
def home():
    return "✅ Gemini chatbot is running!"

@app.route("/chat", methods=["POST"])
def chat():
    data = request.get_json()
    message = data.get("message", "")

    if not message:
        return jsonify({"error": "No message provided"}), 400

    try:
        # ✅ Correct model name for current API (no 'models/' prefix)
        model = genai.GenerativeModel("gemini-1.5-flash")

        # ✅ Correct generation call
        response = model.generate_content(message)

        return jsonify({"reply": response.text.strip()})

    except Exception as e:
        return jsonify({"error": str(e)}), 500

        
@app.route("/ui")
def ui():
    return send_from_directory(".", "index.html")


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.getenv("PORT", 8080)))

