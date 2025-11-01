from flask import Flask, request, jsonify, send_from_directory
import google.generativeai as genai
import os

app = Flask(__name__)

# Configure Gemini API key (must be set in Koyeb Secrets)
genai.configure(api_key=os.getenv("GEMINI_API_KEY"))

@app.route("/")
def home():
    return "✅ Gemini Mini Chatbot is running! Visit /ui to chat."

# 🌐 Chat endpoint
@app.route("/chat", methods=["POST"])
def chat():
    data = request.get_json()
    user_message = data.get("message", "").strip()

    if not user_message:
        return jsonify({"error": "No message provided"}), 400

    try:
        # Choose model (flash = fast, pro = better quality)
        model = genai.GenerativeModel("gemini-1.5-flash")

        # Generate a response
        response = model.generate_content(user_message)

        # Return the text response
        return jsonify({"reply": response.text.strip()})

    except Exception as e:
        return jsonify({"error": str(e)}), 500


# 🧠 List available models (for debugging)
@app.route("/models")
def list_models():
    try:
        models = [m.name for m in genai.list_models()]
        return jsonify(models)
    except Exception as e:
        return jsonify({"error": str(e)})


# 💬 Serve the chat UI page
@app.route("/ui")
def ui():
    return send_from_directory(".", "index.html")


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.getenv("PORT", 8080)))
