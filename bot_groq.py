"""Bot IA en la nube (Groq) con busqueda web, recordatorios y memoria"""
import sys, json, os, time, logging, re, urllib.parse, threading, random
from datetime import datetime, timedelta
from pathlib import Path
import httpx

logging.basicConfig(
    level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s",
    handlers=[logging.StreamHandler()],
)
log = logging.getLogger("bot")

BOT_TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN")
AI_KEY = os.environ.get("GROQ_API_KEY")
if not BOT_TOKEN:
    print("ERROR: Falta TELEGRAM_BOT_TOKEN")
    sys.exit(1)
if not AI_KEY:
    print("ERROR: Falta GROQ_API_KEY")
    sys.exit(1)

API = f"https://api.telegram.org/bot{BOT_TOKEN}"
CHAT_ID = 8507191434
http = httpx.Client(timeout=30, headers={"User-Agent": "Mozilla/5.0"})
last_update = 0

# --- IA via Groq ---
HOY = datetime.now().strftime("%d/%m/%Y")
SYSTEM_PROMPT = f"Eres RyuBot, un asistente util y conversacional. Hoy es {HOY}. Respondes SIEMPRE en espanol, directo y natural. Usas el historial para seguir la conversacion. Si recibes datos extra, usalos para responder con datos concretos."

def ia_chat(messages):
    r = http.post("https://api.groq.com/openai/v1/chat/completions", json={
        "model": "llama-3.3-70b-versatile",
        "messages": messages,
        "max_tokens": 500,
        "temperature": 0.7,
    }, headers={"Authorization": f"Bearer {AI_KEY}", "Content-Type": "application/json"}, timeout=30)
    return r.json()["choices"][0]["message"]["content"].strip()

# --- Busqueda web ---
def _ddg(query):
    try:
        r = http.get(f"https://api.duckduckgo.com/?q={urllib.parse.quote(query)}&format=json&no_html=1&skip_disambig=1", timeout=10)
        if r.status_code == 200:
            d = r.json()
            p = []
            if d.get("AbstractText"): p.append(d["AbstractText"])
            if d.get("Answer"): p.append(d["Answer"])
            if d.get("Definition"): p.append(d["Definition"])
            for t in d.get("RelatedTopics", []):
                if "Text" in t: p.append(t["Text"])
                elif "Topics" in t:
                    for st in t["Topics"]:
                        if "Text" in st: p.append(st["Text"])
            if p: return " | ".join(p[:6])
    except: pass
    return ""

def _ddg_html(query):
    try:
        r = http.get(f"https://html.duckduckgo.com/html/?q={urllib.parse.quote(query)}", timeout=10, follow_redirects=True, headers={"User-Agent": "Mozilla/5.0"})
        if r.status_code == 200:
            snips = re.findall(r'class="result__snippet"[^>]*>(.*?)</a>', r.text, re.DOTALL)
            if snips:
                return " | ".join(re.sub(r'<[^>]+>', '', s).strip() for s in snips[:5])
    except: pass
    return ""

def buscar_web(query):
    baja = query.lower()
    todas = []
    r_html = _ddg_html(query)
    if r_html: todas.append(f"🌐 {r_html}")
    else:
        r = _ddg(query)
        if r: todas.append(f"🌐 {r}")
    r = _ddg_html(f"{query} {HOY.replace('/', ' ')}")
    if r: todas.append(f"📰 {r}")
    if any(w in baja for w in ["pokemon", "pokémon", "pokedex", "wikidex", "nintendo", "switch"]):
        r = _ddg(f"site:wikidex.net {query}")
        if r: todas.append(f"📗 {r}")
        r = _ddg(f"site:nintendo.com {query}")
        if r: todas.append(f"🎮 {r}")
        r = _ddg(f"site:pokemon.com {query}")
        if r: todas.append(f"🎯 {r}")
    if any(w in baja for w in ["github", "codigo", "código", "repositorio", "package", "libreria", "api", "npm", "python", "javascript"]):
        r = _ddg(f"site:github.com {query}")
        if r: todas.append(f"💻 {r}")
        r = _ddg(f"site:stackoverflow.com {query}")
        if r: todas.append(f"🔧 {r}")
        r = _ddg(f"site:docs.python.org {query}")
        if r: todas.append(f"📚 {r}")
    if any(w in baja for w in ["juego", "game", "gaming", "pc", "playstation", "xbox"]):
        r = _ddg(f"site:ign.com {query}")
        if r: todas.append(f"🎮 {r}")
    return "\n\n".join(todas[:6])[:3500] or ""

# --- Memoria ---
historial = []

def recordar(mensaje, respuesta, topico=None):
    historial.append({"msg": mensaje, "resp": respuesta, "topico": topico, "ts": time.time()})
    while len(historial) > 12:
        historial.pop(0)

def _detectar_topico(texto):
    baja = texto.lower()
    if any(w in baja for w in ["tiempo", "clima", "temperatura", "lluvia", "calor", "frio", "soleado", "nublado"]):
        c = re.search(r'(?:en|de|para)\s+(\w+(?:\s+\w+)?)', texto, re.I)
        return f"clima {c.group(1).strip() if c else ''}"
    m = re.search(r'(pok[eé]mon|pokedex)', baja)
    if m: return m.group(0)
    m = re.match(r'(?:que|qué|como|cómo|cuando|cuándo|donde|dónde|por que)\s+(.+)', baja)
    if m: return " ".join(m.group(1).split()[:4])
    return " ".join(baja.split()[:4])

def _reformular_consulta(mensaje):
    if not historial: return mensaje
    baja = mensaje.lower().strip()
    ult_top = (historial[-1].get("topico") or "") or _topico_previo()

    if any(p in baja for p in ["ahora sobre", "ahora quiero", "cambia", "cambiar", "otra cosa", "diferente"]):
        return mensaje

    # Si el ultimo tema era clima, sacar ciudad de cualquier forma
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

def _extraer_ciudad(mensaje):
    m = re.search(r'(?:en|de|para)\s+(\w+(?:\s+\w+)?)', mensaje, re.I)
    return m.group(1).strip().lower() if m else ""

def _sintetizar(info):
    bloques = info.split("\n\n")
    if not bloques: return ""
    textos = []
    for b in bloques[:5]:
        txt = b[2:].strip() if b.startswith(("🌐", "💬", "🐦", "📗", "🎮", "🎯", "💻", "🔧", "📚", "📰")) else b[:400]
        if txt: textos.append(txt[:400])
    if not textos: return ""
    vistos, partes = set(), []
    for t in textos:
        for f in re.split(r'\s*\|\s*', t):
            if len(f) > 20 and f[:60] not in vistos:
                vistos.add(f[:60])
                partes.append(f.strip())
                if len("\n".join(partes)) > 1000: break
    return "\n".join(partes[:8])[:1500]

# --- Clima ---
_wttr = httpx.Client(timeout=8, headers={"User-Agent": "curl/8.0"})
def _clima(consulta, mensaje):
    ciudad = _extraer_ciudad(consulta) or ""
    for c in [ciudad, "Madrid"]:
        if not c: continue
        for fmt in ["%t+%C+%h+%w", "%l:+%t+%C"]:
            try:
                r = _wttr.get(f"https://wttr.in/{urllib.parse.quote(c)}?format={fmt}")
                if r.status_code == 200 and r.text and not r.text.strip().startswith("<!") and len(r.text.strip()) > 3:
                    rta = f"En {c.title()} ahora mismo: {r.text.strip()}"
                    recordar(mensaje, rta, f"clima {c}")
                    return rta
            except: pass
        try:
            r = _wttr.get(f"https://wttr.in/{urllib.parse.quote(c)}?m")
            if r.status_code == 200 and r.text:
                m = re.search(r'(\d+[°]\s*(?:[CF]))\s*([A-Za-z]+)', r.text)
                if m:
                    rta = f"En {c.title()} ahora mismo: {m.group(1)} {m.group(2)}"
                    recordar(mensaje, rta, f"clima {c}")
                    return rta
        except: pass
    rta = f"No pude obtener el tiempo de {ciudad or 'esa ciudad'}."
    recordar(mensaje, rta, f"clima {ciudad or ''}")
    return rta

def generar_respuesta(mensaje):
    consulta = _reformular_consulta(mensaje)
    baja = consulta.lower()

    if any(w in baja for w in ["tiempo", "clima", "temperatura", "lluvia", "calor", "frio", "soleado", "nublado"]):
        return _clima(consulta, mensaje)

    info = buscar_web(consulta)
    ctx = _sintetizar(info) if info else ""

    msgs = [{"role": "system", "content": SYSTEM_PROMPT}]
    for h in historial[-4:]:
        msgs.append({"role": "user", "content": h["msg"]})
        msgs.append({"role": "assistant", "content": h["resp"][:200]})
    prompt = mensaje
    if ctx: prompt += f"\n\nInfo: {ctx[:500]}"
    msgs.append({"role": "user", "content": prompt})

    try:
        rta = ia_chat(msgs)
        if not rta: raise ValueError("Vacia")
        topico = _detectar_topico(consulta)
        recordar(mensaje, rta, topico)
        return rta[:1500]
    except Exception as e:
        log.warning(f"IA fallo: {e}")
        if ctx:
            rta = ctx[:1500]
        else:
            rta = "No encontre informacion sobre eso."
        topico = _detectar_topico(consulta)
        recordar(mensaje, rta, topico)
        return rta

# --- Recordatorios ---
CAL_PATH = "recordatorios.json"
def _cargar_cal():
    global recordatorios
    try:
        if os.path.exists(CAL_PATH):
            with open(CAL_PATH, encoding="utf-8") as f: recordatorios = json.load(f)
    except: recordatorios = []
def _guardar_cal():
    with open(CAL_PATH, "w", encoding="utf-8") as f: json.dump(recordatorios, f, ensure_ascii=False, indent=2)

recordatorios = []
_cargar_cal()

def _procesar_recordatorio(texto):
    baja = texto.lower()
    ahora = datetime.now()

    if any(w in baja for w in ["recordatorio", "recuerda", "avísame", "avisame", "recordame", "acuerdame"]):
        m = re.search(r'(?:recordatorio|recordame|recuerda|avisame|avísame|acuerdame)\s+(?:que\s+)?(.+)', texto, re.I)
        if not m: return "Usa: recordame que <cosa> [en X minutos | a las HH:MM]"
        desc = m.group(1)

        minutos = 0
        m_min = re.search(r'en\s+(\d+)\s*(?:min|minuto|m)', baja)
        m_hora = re.search(r'a\s+las?\s*(\d{1,2})[:.](\d{2})', baja)
        m_hoy = re.search(r'hoy\s+a\s+las?\s*(\d{1,2})[:.](\d{2})', baja)
        m_man = re.search(r'mañana\s+a\s+las?\s*(\d{1,2})[:.](\d{2})', baja)
        m_dia = re.search(r'en\s+(\d+)\s*(?:dia|día|d)', baja)

        if m_min: minutos = int(m_min.group(1))
        elif m_hora and not m_man:
            h, m = int(m_hora.group(1)), int(m_hora.group(2))
            fecha = ahora.replace(hour=h, minute=m, second=0)
            if fecha < ahora: fecha += timedelta(days=1)
            minutos = int((fecha - ahora).total_seconds() / 60)
        elif m_hoy:
            h, m = int(m_hoy.group(1)), int(m_hoy.group(2))
            fecha = ahora.replace(hour=h, minute=m, second=0)
            if fecha < ahora: fecha += timedelta(days=1)
            minutos = int((fecha - ahora).total_seconds() / 60)
        elif m_man:
            h, m = int(m_man.group(1)), int(m_man.group(2))
            fecha = (ahora + timedelta(days=1)).replace(hour=h, minute=m, second=0)
            minutos = int((fecha - ahora).total_seconds() / 60)
        elif m_dia: minutos = int(m_dia.group(1)) * 1440
        else: minutos = 10

        if minutos < 1: minutos = 1
        if minutos > 525600: return "Max 1 año"

        for p in [r'en\s+\d+\s*(?:min|minuto|m)', r'a\s+las?\s*\d{1,2}[:.]\d{2}', r'hoy\s+', r'mañana\s+', r'en\s+\d+\s*(?:dia|día|d)']:
            desc = re.sub(p, '', desc, flags=re.I).strip()

        disp = ahora + timedelta(minutes=minutos)
        recordatorios.append({"id": int(time.time()), "desc": desc, "creado": ahora.isoformat(), "dispara": disp.isoformat(), "minutos": minutos})
        _guardar_cal()
        if minutos < 60: return f"Recordatorio: {desc} (en {minutos} min)"
        elif minutos < 1440: return f"Recordatorio: {desc} (en {minutos//60}h {minutos%60}min)"
        else: return f"Recordatorio: {desc} (en {minutos//1440}d {minutos%1440//60}h)"

    if "lista recordatorios" in baja:
        if not recordatorios: return "No tienes recordatorios."
        out = ["Tus recordatorios:"]
        for r in sorted(recordatorios, key=lambda x: x["dispara"]):
            falta = int((datetime.fromisoformat(r["dispara"]) - ahora).total_seconds()/60)
            out.append(f"{'❌' if falta < 0 else '⏰'} {r['desc']} ({'PASADO' if falta < 0 else f'en {falta}min' if falta < 60 else f'en {falta//60}h{falta%60:02d}min'})")
        return "\n".join(out[:10])

    if "borrar recordatorio" in baja:
        m = re.search(r'(?:borrar|eliminar)\s+(?:el\s+)?(\d+)', baja)
        if m and recordatorios:
            i = int(m.group(1)) - 1
            if 0 <= i < len(recordatorios):
                e = recordatorios.pop(i); _guardar_cal(); return f"Eliminado: {e['desc']}"
        return "Usa: borrar recordatorio NUMERO"
    return None

def _revisar_recordatorios():
    while True:
        try:
            _cargar_cal()
            ahora = datetime.now()
            for r in [r for r in recordatorios if datetime.fromisoformat(r["dispara"]) <= ahora]:
                http.post(f"{API}/sendMessage", json={"chat_id": CHAT_ID, "text": f"⏰ RECORDATORIO: {r['desc']}"})
                recordatorios.remove(r); _guardar_cal()
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
                        log.info(f"→ {texto[:60]}")
                        try:
                            resp = _procesar_recordatorio(texto) or generar_respuesta(texto)
                            if resp:
                                http.post(f"{API}/sendMessage", json={"chat_id": CHAT_ID, "text": resp})
                        except Exception as e:
                            log.error(f"Resp error: {e}")
        except Exception as e:
            log.error(f"Poll error: {e}")
            time.sleep(3)

if __name__ == "__main__":
    poll()
