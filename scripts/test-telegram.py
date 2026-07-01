"""Prueba rapida de conexion Telegram sin OpenCode"""
import json
import os
import sys

TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN", "")
if not TOKEN:
    TOKEN = input("Pega tu token de Telegram: ").strip()

import httpx

r = httpx.get(f"https://api.telegram.org/bot{TOKEN}/getMe")
if r.json().get("ok"):
    bot = r.json()["result"]
    print(f"Bot conectado: @{bot['username']}")
    print("Enviale un mensaje desde Telegram y vuelve aqui.")
    input("Presiona Enter cuando hayas enviado el mensaje...")
    updates = httpx.get(f"https://api.telegram.org/bot{TOKEN}/getUpdates").json()
    if updates.get("result"):
        chat_id = updates["result"][0]["message"]["chat"]["id"]
        print(f"Chat ID detectado: {chat_id}")
        httpx.post(f"https://api.telegram.org/bot{TOKEN}/sendMessage",
            json={"chat_id": chat_id, "text": "Conexion exitosa! Tu agente personal ya esta listo."})
        print("Mensaje de prueba enviado. Revisa Telegram!")
    else:
        print("No se recibio ningun mensaje. Enviaste /start al bot?")
else:
    print(f"Error: {r.json()}")
