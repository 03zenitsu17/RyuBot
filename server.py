"""Servidor web que mantiene el bot vivo en Render"""
import threading, os
from flask import Flask
from bot_groq import poll

# Arrancar bot al importar (Gunicorn no ejecuta __main__)
threading.Thread(target=poll, daemon=True).start()

app = Flask(__name__)

@app.route("/")
@app.route("/health")
def health():
    return "OK", 200

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 8080))
    app.run(host="0.0.0.0", port=port)
