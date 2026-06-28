"""Bot IA (Groq Llama 3) con busqueda por temas y recordatorios IA"""
import sys, os, time, logging, re, json, urllib.parse, threading
from datetime import datetime, timedelta
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
SYS_BASE = "Eres RyuBot, un asistente util y conversacional en espanol. Hoy es {hoy}. Respondes natural y directo. Usas el historial para seguir la conversacion."

SYS_CLIMA = (
    "Eres RyuBot, un asistente util y conversacional en espanol. Hoy es {hoy}. "
    "Cuando te pregunten por el clima SIGUE estas reglas:\n"
    "1. NUNCA menciones fuentes, paginas web, sitios, ni sugieras buscar en internet.\n"
    "2. NUNCA inventes el clima. Responde solo con los datos que te doy.\n"
    "3. Responde breve: temperatura actual, maxima/minima del dia, si va a llover.\n"
    "4. Si piden mas detalle (varios dias, viento, humedad), amplialo.\n"
    "5. Por defecto asume Madrid, salvo que digan otra ciudad.\n"
    "Usas el historial para seguir la conversacion."
)

SYS_GAMING = (
    "Eres RyuBot, un asistente util y conversacional en espanol. Hoy es {hoy}. "
    "Cuando te pregunten sobre juegos, consolas, rumores o noticias SIGUE estas reglas:\n"
    "1. Busca informacion actualizada en los datos que te doy, nunca respondas solo de memoria si el tema puede haber cambiado.\n"
    "2. Cuando te pida opinion de la comunidad, busca en los datos que te doy y resume: sentimiento general, argumentos repetidos, controversias.\n"
    "3. Las fuentes fiables segun el tema vienen en los datos. Si una fuente es poco fiable o rumor sin confirmar, dimelo.\n"
    "4. Da respuestas organizadas: si hay fuentes con opiniones distintas, separalas.\n"
    "5. Por defecto se conciso, si piden analisis profundo amplia.\n"
    "Usas el historial para seguir la conversacion."
)

SYS_RECORDATORIO = (
    "Eres RyuBot, un asistente util y conversacional en espanol. Hoy es {hoy}. "
    "Cuando te pidan crear un recordatorio, alarma o notificacion, responde SOLO con JSON valido, sin texto adicional. "
    "Hoy es {hoy}. Calcula fechas relativas (manana, viernes, en 3 dias) basandote en esto.\n"
    "Si la fecha/hora es ambigua, usa accion 'pedir_aclaracion'.\n\n"
    "Formato:\n"
    '{{\n'
    '  "accion": "crear_recordatorio",\n'
    '  "titulo": "string breve",\n'
    '  "fecha": "YYYY-MM-DD",\n'
    '  "hora": "HH:MM",\n'
    '  "repetir": "ninguno | diario | semanal | mensual | anual",\n'
    '  "categoria": "personal | ryu_store | gaming | administrativo | salud",\n'
    '  "prioridad": "normal | alta",\n'
    '  "aviso_previo": minutos\n'
    '}}\n\n'
    "Para listar: accion 'listar_recordatorios'. Para borrar: accion 'borrar_recordatorio' con campo 'id' o 'titulo'.\n"
    "Para pedir aclaracion: accion 'pedir_aclaracion' con campo 'pregunta'.\n"
    "Si no es un recordatorio, responde de forma natural y conversacional."
)

def ia_chat(messages):
    r = http.post("https://api.groq.com/openai/v1/chat/completions", json={
        "model": "llama-3.3-70b-versatile",
        "messages": messages,
        "max_tokens": 600,
        "temperature": 0.7,
    }, headers={"Authorization": f"Bearer {AI_KEY}", "Content-Type": "application/json"}, timeout=30)
    return r.json()["choices"][0]["message"]["content"].strip()

# --- Busqueda web ---
def _ddg_html(query):
    try:
        r = http.get(f"https://html.duckduckgo.com/html/?q={urllib.parse.quote(query)}", timeout=10, follow_redirects=True)
        if r.status_code == 200:
            snips = re.findall(r'class="result__snippet"[^>]*>(.*?)</a>', r.text, re.DOTALL)
            if snips:
                return " | ".join(re.sub(r'<[^>]+>', '', s).strip() for s in snips[:5])
    except: pass
    return ""

# --- Clima via wttr.in ---
def _clima(ciudad):
    try:
        r = http.get(f"https://wttr.in/{urllib.parse.quote(ciudad)}?format=%t+%C+%h+%w", timeout=8, headers={"User-Agent": "curl/8.0"})
        if r.status_code == 200 and r.text and not r.text.startswith("<!") and len(r.text.strip()) > 3:
            return r.text.strip()
    except: pass
    try:
        r = http.get(f"https://wttr.in/{urllib.parse.quote(ciudad)}?format=%l:+%t+%C", timeout=8, headers={"User-Agent": "curl/8.0"})
        if r.status_code == 200 and r.text and not r.text.startswith("<!") and len(r.text.strip()) > 3:
            return r.text.strip()
    except: pass
    return ""

# --- Recordatorios ---
CAL_PATH = "recordatorios.json"
recordatorios = []

def _cargar_cal():
    global recordatorios
    try:
        if os.path.exists(CAL_PATH):
            with open(CAL_PATH, encoding="utf-8") as f: recordatorios = json.load(f)
    except: recordatorios = []

def _guardar_cal():
    with open(CAL_PATH, "w", encoding="utf-8") as f: json.dump(recordatorios, f, ensure_ascii=False, indent=2)

_cargar_cal()

def _ejecutar_recordatorio_json(j, mensaje):
    ahora = datetime.now()
    fecha_str = j.get("fecha", ahora.strftime("%Y-%m-%d"))
    hora_str = j.get("hora", ahora.strftime("%H:%M"))
    try:
        disparo = datetime.strptime(f"{fecha_str} {hora_str}", "%Y-%m-%d %H:%M")
    except:
        return "No entendi la fecha/hora. Usa formato YYYY-MM-DD HH:MM"

    r = {
        "id": int(time.time()),
        "titulo": j.get("titulo", "Recordatorio"),
        "fecha": fecha_str,
        "hora": hora_str,
        "dispara": disparo.isoformat(),
        "repetir": j.get("repetir", "ninguno"),
        "categoria": j.get("categoria", "personal"),
        "prioridad": j.get("prioridad", "normal"),
        "aviso_previo": j.get("aviso_previo", 0),
        "creado": ahora.isoformat(),
    }
    recordatorios.append(r)
    _guardar_cal()

    falta = int((disparo - ahora).total_seconds() / 60)
    if falta < 1:
        return f"Recordatorio creado: {r['titulo']} (ya mismo!)"
    elif falta < 60:
        return f"Recordatorio creado: {r['titulo']} (en {falta} min)"
    elif falta < 1440:
        return f"Recordatorio creado: {r['titulo']} (en {falta//60}h{falta%60:02d}min)"
    else:
        return f"Recordatorio creado: {r['titulo']} ({fecha_str} a las {hora_str})"

def _procesar_json_recordatorio(texto):
    # Extraer JSON del texto (puede venir con backticks o rodeado de texto)
    m = re.search(r'\{.*"accion".*\}', texto, re.DOTALL)
    if not m: return None
    try:
        j = json.loads(m.group(0))
    except: return None

    accion = j.get("accion")
    if accion == "crear_recordatorio":
        return _ejecutar_recordatorio_json(j, texto)
    elif accion == "listar_recordatorios":
        if not recordatorios: return "No tienes recordatorios."
        lines = ["Tus recordatorios:"]
        for i, r in enumerate(sorted(recordatorios, key=lambda x: x["dispara"]), 1):
            d = datetime.fromisoformat(r["dispara"])
            lines.append(f"{i}. {r['titulo']} - {d.strftime('%d/%m %H:%M')} [{r['categoria']}]")
        return "\n".join(lines)
    elif accion == "borrar_recordatorio":
        idx = j.get("id")
        tit = j.get("titulo", "").lower()
        for i, r in enumerate(recordatorios):
            if (idx and r["id"] == idx) or (tit and tit in r["titulo"].lower()):
                e = recordatorios.pop(i)
                _guardar_cal()
                return f"Borrado: {e['titulo']}"
        return "No encontre ese recordatorio."
    elif accion == "pedir_aclaracion":
        return f"❓ {j.get('pregunta', 'Necesito mas detalles.')}"
    return None

# --- Memoria ---
historial = []

def recordar(mensaje, respuesta, topico=None):
    historial.append({"msg": mensaje, "resp": respuesta, "topico": topico, "ts": time.time()})
    while len(historial) > 12:
        historial.pop(0)

PALABRAS_CLIMA = ["tiempo", "clima", "temperatura", "lluvia", "calor", "frio", "soleado", "nublado", "paraguas", "humedad", "viento"]
PALABRAS_GAMING = [
    "juego", "jugar", "videojuego", "consola", "nintendo", "playstation", "xbox", "pc gaming",
    "steam", "switch", "ps5", "ps4", "series x", "game pass",
    "rumor", "filtracion", "filtracion", "noticia gaming", "lanzamiento",
    "gta", "pokemon", "zelda", "mario", "final fantasy", "call of duty", "fortnite", "minecraft",
    "digital foundry", "ign", "eurogamer", "vgc", "resetera", "nate", "genki", "tom henderson",
    "review", "analisis", "analisis", "graficos", "graficos", "fps", "resolucion",
    "ventas", "mercado", "famitsu", "npd", "circana", "vgchartz",
    "actualizacion", "parche", "update", "nerf", "buff", "nerfeo",
    "e3", "nintendo direct", "state of play", "xbox showcase", "gamescom", "geoff keighley",
    "metacritic", "opencritic", "nota", "puntuacion", "puntuacion",
]
PALABRAS_RECORDATORIO = [
    "recordatorio", "recuerda", "recuerdame", "avisame", "avísame", "alarma",
    "notificame", "notificacion", "notificacion", "acuerdame", "recordame",
    "cita", "reunion", "reunion", "tarea", "pendiente", "plazo", "vencimiento",
    "sepe", "labora", "seguridad social", "tramite", "tramite", "administrativo",
]

def _detectar_topico(texto):
    baja = texto.lower()
    if any(w in baja for w in PALABRAS_RECORDATORIO):
        return "recordatorio"
    if any(w in baja for w in PALABRAS_CLIMA):
        c = re.search(r'(?:en|de|para)\s+(\w+(?:\s+\w+)?)', texto, re.I)
        return f"clima {c.group(1).strip() if c else ''}"
    if any(w in baja for w in PALABRAS_GAMING):
        return "gaming"
    m = re.match(r'(?:que|qué|como|cómo|cuando|cuándo|donde|dónde|por que)\s+(.+)', baja)
    if m: return " ".join(m.group(1).split()[:4])
    return " ".join(baja.split()[:4])

def _reformular_consulta(mensaje):
    if not historial: return mensaje
    baja = mensaje.lower().strip()
    ult_top = (historial[-1].get("topico") or "") or _topico_previo()

    if any(p in baja for p in ["ahora sobre", "ahora quiero", "cambia", "cambiar", "otra cosa", "diferente"]):
        return mensaje

    if ult_top.startswith("clima"):
        limpio = baja
        for p in ["tiempo en", "tiempo de", "tiempo para", "clima en", "clima de"]:
            limpio = re.sub(r'^y?\s*' + re.escape(p) + r'\s*', '', limpio).strip()
        if limpio == baja:
            limpio = re.sub(r'^(?:y\s+|y\s*)?(?:en|de|para|del|de la)?\s*', '', baja).strip()
        if limpio and len(limpio.split()) <= 2 and not any(w in limpio for w in ["tiempo", "clima", "que", "como", "cuando", "donde"]):
            return f"tiempo en {limpio}"

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

def _extraer_ciudad(texto):
    m = re.search(r'(?:en|de|para)\s+(\w+(?:\s+\w+)?)', texto, re.I)
    return m.group(1).strip().lower() if m else ""

def _buscar_gaming(query):
    r = _ddg_html(query)
    if r: return r
    r = _ddg_html(f"{query} 2026")
    if r: return r
    return ""

def _es_recordatorio(texto):
    baja = texto.lower()
    if any(w in baja for w in PALABRAS_RECORDATORIO):
        return True
    # Detectar frases como "que tenga que..." o "el viernes a las..."
    if re.search(r'(mañana|pasado mañana|el lunes|el martes|el miercoles|el jueves|el viernes|el sabado|el domingo|el \d+|a las \d+|en \d+ (min|hora|dia|día|minuto))', baja):
        if any(w in baja for w in ["tengo", "hay que", "que hacer", "cita", "reunion", "reunión", "plazo"]):
            return True
    return False

def generar_respuesta(mensaje):
    hoy = datetime.now().strftime("%d/%m/%Y")
    consulta = _reformular_consulta(mensaje)

    # 1. Detectar si es recordatorio
    if _es_recordatorio(consulta):
        sys_p = SYS_RECORDATORIO.format(hoy=hoy)
        msgs = [{"role": "system", "content": sys_p}]
        for h in historial[-3:]:
            msgs.append({"role": "user", "content": h["msg"]})
            msgs.append({"role": "assistant", "content": h["resp"][:200]})
        msgs.append({"role": "user", "content": mensaje})
        try:
            rta = ia_chat(msgs)
            if not rta: raise ValueError("Vacia")
            resultado = _procesar_json_recordatorio(rta)
            if resultado:
                recordar(mensaje, resultado, "recordatorio")
                return resultado
        except Exception as e:
            log.warning(f"Recordatorio fallo: {e}")

    # 2. Detectar otros temas
    baja = consulta.lower()
    es_clima = any(w in baja for w in PALABRAS_CLIMA)
    es_gaming = any(w in baja for w in PALABRAS_GAMING)

    ctx = ""
    sys_p = SYS_BASE.format(hoy=hoy)

    if es_clima:
        ciudad = _extraer_ciudad(consulta) or "Madrid"
        ctx = _clima(ciudad)
        sys_p = SYS_CLIMA.format(hoy=hoy)
    elif es_gaming:
        ctx = _buscar_gaming(consulta)
        sys_p = SYS_GAMING.format(hoy=hoy)

    msgs = [{"role": "system", "content": sys_p}]
    for h in historial[-4:]:
        msgs.append({"role": "user", "content": h["msg"]})
        msgs.append({"role": "assistant", "content": h["resp"][:200]})

    prompt = mensaje
    if ctx:
        prompt += f"\n[Info: {ctx}]"
    msgs.append({"role": "user", "content": prompt})

    try:
        rta = ia_chat(msgs)
        if not rta: raise ValueError("Vacia")
        topico = _detectar_topico(consulta)
        recordar(mensaje, rta, topico)
        return rta[:2000]
    except Exception as e:
        log.warning(f"IA fallo: {e}")
        rta = "Lo siento, no pude procesar eso."
        recordar(mensaje, rta)
        return rta

# --- Hilo de recordatorios ---
def _revisar_recordatorios():
    while True:
        try:
            _cargar_cal()
            ahora = datetime.now()
            for r in [r for r in recordatorios if datetime.fromisoformat(r["dispara"]) <= ahora]:
                msg = f"⏰ RECORDATORIO: {r['titulo']} [{r['categoria']}]"
                http.post(f"{API}/sendMessage", json={"chat_id": CHAT_ID, "text": msg})
                recordatorios.remove(r)
                _guardar_cal()
        except: pass
        time.sleep(30)

threading.Thread(target=_revisar_recordatorios, daemon=True).start()

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