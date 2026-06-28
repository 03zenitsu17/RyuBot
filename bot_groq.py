"""Bot IA puro (Groq Llama 3) - solo conversacion"""
import sys, os, time, logging, re, urllib.parse, threading
from datetime import datetime
import httpx

logging.basicConfig(
    level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s",
    handlers=[logging.StreamHandler()],
)
log = logging.getLogger("bot")

BOT_TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN")
AI_KEY = os.environ.get("GROQ_API_KEY")
if not BOT_TOKEN:
    print("ERROR: Falta TELEGRAM_BOT_TOKEN"); sys.exit(1)
if not AI_KEY:
    print("ERROR: Falta GROQ_API_KEY"); sys.exit(1)

API = f"https://api.telegram.org/bot{BOT_TOKEN}"
CHAT_ID = 8507191434
http = httpx.Client(timeout=30, headers={"User-Agent": "Mozilla/5.0"})
last_update = 0

# --- IA via Groq ---
SYSTEM_PROMPT = "Eres RyuBot, un asistente util y conversacional en espanol. Hoy es {hoy}. Respondes natural y directo. Usas el historial para seguir la conversacion."

def ia_chat(messages):
    r = http.post("https://api.groq.com/openai/v1/chat/completions", json={
        "model": "llama-3.3-70b-versatile",
        "messages": messages,
        "max_tokens": 500,
        "temperature": 0.7,
    }, headers={"Authorization": f"Bearer {AI_KEY}", "Content-Type": "application/json"}, timeout=30)
    return r.json()["choices"][0]["message"]["content"].strip()

# --- Memoria ---
historial = []

def recordar(mensaje, respuesta, topico=None):
    historial.append({"msg": mensaje, "resp": respuesta, "topico": topico, "ts": time.time()})
    while len(historial) > 12:
        historial.pop(0)

def _detectar_topico(texto):
    baja = texto.lower()
    m = re.match(r'(?:que|qué|como|cómo|cuando|cuándo|donde|dónde|por que)\s+(.+)', baja)
    if m: return " ".join(m.group(1).split()[:4])
    return " ".join(baja.split()[:4])

def _reformular_consulta(mensaje):
    if not historial: return mensaje
    baja = mensaje.lower().strip()
    ult_top = (historial[-1].get("topico") or "") or _topico_previo()

    if any(p in baja for p in ["ahora sobre", "ahora quiero", "cambia", "cambiar", "otra cosa", "diferente"]):
        return mensaje

    if baja.startswith("pero "):
        return mensaje

    if baja.startswith(("y ", "entonces ", "tambien ", "también ")):
        resto = re.sub(r'^(?:y|entonces|tambien|también)\s+', '', baja)
        return f"{ult_top} {resto}" if ult_top else mensaje

    m = re.match(r'(?:y\s+)?(?:en|de|para)\s+(.+?)\s*\??$', baja)
    if m:
        return f"{ult_top} en {m.group(1)}" if ult_top else mensaje
    m = re.match(r'(?:el|la|los|las|del|de la|sus)\s+(.+)$', baja)
    if m and ult_top:
        return f"{ult_top} {m.group(1)}"
    if len(baja.split()) <= 4:
        if baja in ["dime mas", "dime más", "sigue", "continua", "continúa", "más info", "mas info"]:
            return f"{ult_top} mas informacion" if ult_top else mensaje
    return mensaje

def _topico_previo():
    for h in reversed(historial):
        if h.get("topico"): return h["topico"]
    return ""

def generar_respuesta(mensaje):
    hoy = datetime.now().strftime("%d/%m/%Y")
    consulta = _reformular_consulta(mensaje)

    msgs = [{"role": "system", "content": SYSTEM_PROMPT.format(hoy=hoy)}]
    for h in historial[-4:]:
        msgs.append({"role": "user", "content": h["msg"]})
        msgs.append({"role": "assistant", "content": h["resp"][:200]})
    msgs.append({"role": "user", "content": mensaje})

    try:
        rta = ia_chat(msgs)
        if not rta: raise ValueError("Vacia")
        topico = _detectar_topico(consulta)
        recordar(mensaje, rta, topico)
        return rta[:1500]
    except Exception as e:
        log.warning(f"IA fallo: {e}")
        rta = "Lo siento, no pude procesar eso."
        recordar(mensaje, rta)
        return rta

# --- Polling ---
def poll():
    global last_update
    log.info("Bot iniciado.")
    while True:
        try:
            r = http.get(f"{API}/getUpdates", params={"offset": last_update + 1, "timeout": 30})
            data = r.json()
            if data.get("ok"):
                for upd in data["result"]:
                    last_update = upd["update_id"]
                    msg = upd.get("message") or upd.get("edited_message")
                    if msg and msg.get("text") and msg["chat"]["id"] == CHAT_ID:
                        texto = msg["text"].strip()
                        if texto.startswith("/"): continue
                        log.info(f"\u2192 {texto[:60]}")
                        try:
                            resp = generar_respuesta(texto)
                            if resp:
                                http.post(f"{API}/sendMessage", json={"chat_id": CHAT_ID, "text": resp})
                        except Exception as e:
                            log.error(f"Resp error: {e}")
        except Exception as e:
            log.error(f"Poll error: {e}")
            time.sleep(3)

if __name__ == "__main__":
    poll()