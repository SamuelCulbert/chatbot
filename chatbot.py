from flask import Flask, request, jsonify
import os
import openai
app = Flask(__name__)
open.api_key = os.getenv("OPEN_API_KEY")
@app.route("/")
def home():
    return "mini chatbot is running on koyeb!"

@app.route("/chat", methods=["POST"])
def chat():
    data = request.get_json()
    message = data.get("message", "")

    if not message:
        return jsonify({"error": "No message provided"}), 400

    try:
        response = openai.ChatCompletion.create(
            model="gpt-3.5-turbo",
            messages=[{"role": "user", "content": message}]
        )
        reply = response.choices[0].message.content.strip()
        return jsonify({"reply": reply})

    except Exception as e:
        return jsonify({"error": str(e)}), 500

if __name__ == "__main__":

    app.run(host="0.0.0.0", port=int(os.getenv("PORT", 8080)))

