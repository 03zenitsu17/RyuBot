"""Bot IA (Groq Llama 3) con busqueda, recordatorios y Gmail"""
import sys, os, time, logging, re, json, urllib.parse, threading, base64
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

# --- Gmail ---
GMAIL_TOKEN_B64 = os.environ.get("GMAIL_TOKEN_B64")
_gmail_service = None

def _init_gmail():
    global _gmail_service
    if not GMAIL_TOKEN_B64:
        log.info("GMAIL_TOKEN_B64 no configurado")
        return None
    if _gmail_service:
        return _gmail_service
    try:
        from google.auth.transport.requests import Request
        from google.oauth2.credentials import Credentials
        from googleapiclient.discovery import build
        token_data = json.loads(base64.b64decode(GMAIL_TOKEN_B64).decode())
        creds = Credentials.from_authorized_user_info(token_data, ["https://www.googleapis.com/auth/gmail.readonly", "https://www.googleapis.com/auth/gmail.compose"])
        if creds.expired and creds.refresh_token:
            creds.refresh(Request())
        _gmail_service = build("gmail", "v1", credentials=creds)
        return _gmail_service
    except Exception as e:
        log.warning(f"Gmail init error: {e}")
        return None

_ultima_lista_emails = []  # [(id, from, subject)]

def _h(text):
    """Escapa HTML"""
    return text.replace("&","&amp;").replace("<","&lt;").replace(">","&gt;")

def _leer_inbox(max_r=20, filtro="", solo_no_leidos=True, solo_ultimo=False):
    svc = _init_gmail()
    if not svc: return "Gmail no conectado."
    try:
        labels = ["INBOX"]
        if solo_no_leidos: labels.append("UNREAD")
        params = {"userId": "me", "labelIds": labels, "maxResults": min(max_r, 50)}
        if filtro: params["q"] = filtro
        r = svc.users().messages().list(**params).execute()
        msgs = r.get("messages", [])
        if not msgs:
            msg = f"No hay emails que coincidan con '{filtro}'." if filtro else "No tienes emails."
            return msg
        global _ultima_lista_emails
        res = []
        _ultima_lista_emails = []
        for i, m in enumerate(msgs[:max_r], 1):
            d = svc.users().messages().get(userId="me", id=m["id"], format="metadata", metadataHeaders=["From", "Subject", "Date"]).execute()
            hd = {h["name"]: h["value"] for h in d.get("payload", {}).get("headers", [])}
            _de = _h(hd.get("From","?"))
            _asunto = _h(hd.get("Subject","?"))
            _fecha = _h(hd.get("Date","?"))
            _ultima_lista_emails.append((m["id"], hd.get("From","?"), hd.get("Subject","?")))
            res.append(f"<b>{i}.</b> <b>De:</b> {_de}\n    <b>Asunto:</b> {_asunto}\n    <i>{_fecha}</i>")
        titulo = f"<b>📬 Emails {'con ' + _h(filtro) if filtro else ''}:</b>"
        return titulo + "\n" + "\n─────────────\n".join(res[:max_r])
    except Exception as e:
        return f"Error al leer email: {e}"

def _leer_cuerpo(email_id):
    svc = _init_gmail()
    if not svc: return "Gmail no conectado."
    try:
        d = svc.users().messages().get(userId="me", id=email_id, format="full").execute()
        h = {h["name"]: h["value"] for h in d.get("payload", {}).get("headers", [])}
        cuerpo = ""
        parts = d.get("payload", {}).get("parts", [])
        if not parts and d.get("payload", {}).get("body", {}).get("data"):
            cuerpo = d["payload"]["body"]["data"]
        else:
            for p in parts:
                if p["mimeType"] == "text/plain" and p.get("body", {}).get("data"):
                    cuerpo = p["body"]["data"]
                    break
        if cuerpo:
            cuerpo = base64.urlsafe_b64decode(cuerpo).decode("utf-8", errors="replace")[:1000]
        _de = _h(h.get("From","?"))
        _asunto = _h(h.get("Subject","?"))
        _cuerpo = _h(cuerpo)
        return f"<b>De:</b> {_de}\n<b>Asunto:</b> {_asunto}\n\n{_cuerpo}"
    except Exception as e:
        return f"<b>Error:</b> {_h(str(e))}"

def _crear_borrador_respuesta(email_id, cuerpo_respuesta):
    """Crea borrador de respuesta a un email existente"""
    svc = _init_gmail()
    if not svc: return "Gmail no conectado."
    try:
        orig = svc.users().messages().get(userId="me", id=email_id, format="metadata", metadataHeaders=["From", "Subject", "Message-ID", "References"]).execute()
        h = {h["name"]: h["value"] for h in orig.get("payload", {}).get("headers", [])}
        para = h.get("From", "")
        asunto = h.get("Subject", "")
        if not asunto.startswith("Re: "): asunto = f"Re: {asunto}"
        msg_id = h.get("Message-ID", "")
        refs = h.get("References", "") or msg_id
        msg = (
            f"From: me\r\nTo: {para}\r\nSubject: {asunto}\r\n"
            f"In-Reply-To: {msg_id}\r\nReferences: {refs}\r\n"
            f"MIME-Version: 1.0\r\nContent-Type: text/plain; charset=UTF-8\r\n\r\n{cuerpo_respuesta}"
        )
        raw = base64.urlsafe_b64encode(msg.encode("utf-8")).decode()
        draft = svc.users().drafts().create(userId="me", body={"message": {"raw": raw}}).execute()
        return f"✅ Borrador respuesta creado para:\n<b>Asunto:</b> {_h(h.get('Subject','?'))}"
    except Exception as e:
        return f"<b>Error:</b> {_h(str(e))}"

def _crear_borrador_nuevo(para, asunto, cuerpo):
    svc = _init_gmail()
    if not svc: return "Gmail no conectado."
    try:
        msg = (f"From: me\r\nTo: {para}\r\nSubject: {asunto}\r\nMIME-Version: 1.0\r\nContent-Type: text/plain; charset=UTF-8\r\n\r\n{cuerpo}")
        raw = base64.urlsafe_b64encode(msg.encode("utf-8")).decode()
        draft = svc.users().drafts().create(userId="me", body={"message": {"raw": raw}}).execute()
        return f"Borrador creado: '{asunto}' para {para}"
    except Exception as e:
        return f"Error: {e}"

def _listar_borradores():
    svc = _init_gmail()
    if not svc: return "Gmail no conectado."
    try:
        r = svc.users().drafts().list(userId="me", maxResults=10).execute()
        drafts = r.get("drafts", [])
        if not drafts: return "📭 No tienes borradores."
        res = []
        for i, d in enumerate(drafts, 1):
            m = svc.users().messages().get(userId="me", id=d["message"]["id"], format="metadata", metadataHeaders=["To", "Subject"]).execute()
            h = {h["name"]: h["value"] for h in m.get("payload", {}).get("headers", [])}
            res.append(f"<b>{i}.</b> Para: {_h(h.get('To','?'))}\n    Asunto: {_h(h.get('Subject','?'))}")
        return "📝 <b>Borradores:</b>\n" + "\n─────────────\n".join(res)
    except Exception as e:
        return f"<b>Error:</b> {_h(str(e))}"

def _borrar_borrador(criterio):
    svc = _init_gmail()
    if not svc: return "Gmail no conectado."
    try:
        r = svc.users().drafts().list(userId="me", maxResults=20).execute()
        for d in r.get("drafts", []):
            m = svc.users().messages().get(userId="me", id=d["message"]["id"], format="metadata", metadataHeaders=["To", "Subject"]).execute()
            h = {h["name"]: h["value"] for h in m.get("payload", {}).get("headers", [])}
            texto = f"{h.get('To','')} {h.get('Subject','')}".lower()
            if criterio.lower() in texto:
                svc.users().drafts().delete(userId="me", id=d["id"]).execute()
                return f"🗑️ <b>Borrador eliminado:</b> {_h(h.get('Subject','?'))}"
        return "No encontre un borrador con ese criterio."
    except Exception as e:
        return f"<b>Error:</b> {_h(str(e))}"

def _email_por_numero(n):
    global _ultima_lista_emails
    if 1 <= n <= len(_ultima_lista_emails):
        return _ultima_lista_emails[n-1][0]
    return None

def _buscar_email_id(termino):
    """Devuelve el ID del primer email no leido que coincida"""
    svc = _init_gmail()
    if not svc: return None
    try:
        from googleapiclient.errors import HttpError
        r = svc.users().messages().list(userId="me", labelIds=["INBOX", "UNREAD"], q=termino, maxResults=1).execute()
        msgs = r.get("messages", [])
        if msgs: return msgs[0]["id"]
    except: pass
    return None

def _buscar_importantes():
    svc = _init_gmail()
    if not svc: return []
    keywords = ["hacienda", "sepe", "labora", "seguridad social", "banco", "factura", "urgente", "importante"]
    try:
        r = svc.users().messages().list(userId="me", labelIds=["INBOX", "UNREAD"], maxResults=10).execute()
        importantes = []
        for m in r.get("messages", []):
            d = svc.users().messages().get(userId="me", id=m["id"], format="metadata", metadataHeaders=["From", "Subject"]).execute()
            h = {h["name"]: h["value"] for h in d.get("payload", {}).get("headers", [])}
            asunto = h.get("Subject", "").lower()
            remitente = h.get("From", "").lower()
            texto = f"{asunto} {remitente}"
            if any(k in texto for k in keywords):
                importantes.append(f"📧 {h['Subject']} - {h['From']}")
        return importantes
    except: return []

# --- IA via Groq ---
SYS_BASE = "Eres RyuBot, un asistente util y conversacional en espanol. Hoy es {hoy}. NUNCA uses ** ni asteriscos. Cuando recomiendes algo (libro, juego, pelicula, etc) usa SIEMPRE este formato:\n\n-titulo-\nexplicacion del contenido\n\npor que lo recomiendo\n\ncosas buenas y malas\n\nFuente: autor/creador/sitio\n\nSepara secciones con linea en blanco. Usa emojis apropiados. Usas el historial para seguir la conversacion."

SYS_CLIMA = (
    "Eres RyuBot, un asistente util y conversacional en espanol. Hoy es {hoy}. "
    "Cuando te pregunten por el clima:\n"
    "1. NUNCA menciones fuentes ni paginas web.\n"
    "2. NUNCA inventes. Responde solo con los datos que te doy.\n"
    "3. NUNCA uses ** ni -titulo- ni formatos especiales.\n"
    "4. Responde breve: temperatura, maxima/minima, lluvia. Usa emojis.\n"
    "5. Por defecto Madrid, salvo que digan otra ciudad.\n"
)

SYS_GAMING = (
    "Eres RyuBot, un asistente util y conversacional en espanol. Hoy es {hoy}. "
    "Cuando te pregunten sobre juegos:\n"
    "1. Busca info actualizada en los datos que te doy.\n"
    "2. NUNCA uses ** ni -titulo- ni formatos especiales. Usa emojis.\n"
    "3. Si una fuente es poco fiable, dimelo.\n"
    "4. Indica al final: Fuente: [nombre de la fuente].\n"
    "5. Separa listas con linea en blanco.\n"
    "6. NUNCA menciones paginas web.\n"
)

SYS_RECORDATORIO = (
    "Eres RyuBot, un asistente util y conversacional en espanol. Hoy es {hoy}. "
    "Cuando te pidan crear un recordatorio, alarma o notificacion, responde SOLO con JSON valido, sin texto adicional. "
    "Hoy es {hoy}. Calcula fechas relativas (manana, viernes, en 3 dias).\n"
    "Si la fecha/hora es ambigua, usa accion 'pedir_aclaracion'.\n\n"
    "Formato:\n"
    '{\n'
    '  "accion": "crear_recordatorio",\n'
    '  "titulo": "string breve",\n'
    '  "fecha": "YYYY-MM-DD",\n'
    '  "hora": "HH:MM",\n'
    '  "repetir": "ninguno | diario | semanal | mensual | anual",\n'
    '  "categoria": "personal | ryu_store | gaming | administrativo | salud",\n'
    '  "prioridad": "normal | alta",\n'
    '  "aviso_previo": minutos\n'
    '}\n\n'
    "Para listar: accion 'listar_recordatorios'. Para borrar: accion 'borrar_recordatorio' con 'id' o 'titulo'.\n"
    "Para pedir aclaracion: accion 'pedir_aclaracion' con 'pregunta'.\n"
    "Si no es un recordatorio, responde normal."
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
        return "No entendi la fecha/hora."
    r = {
        "id": int(time.time()), "titulo": j.get("titulo", "Recordatorio"),
        "fecha": fecha_str, "hora": hora_str, "dispara": disparo.isoformat(),
        "repetir": j.get("repetir", "ninguno"), "categoria": j.get("categoria", "personal"),
        "prioridad": j.get("prioridad", "normal"), "aviso_previo": j.get("aviso_previo", 0),
        "creado": ahora.isoformat(),
    }
    recordatorios.append(r)
    _guardar_cal()
    falta = int((disparo - ahora).total_seconds() / 60)
    if falta < 1: return f"Recordatorio: {r['titulo']} (ya mismo)"
    elif falta < 60: return f"Recordatorio: {r['titulo']} (en {falta} min)"
    elif falta < 1440: return f"Recordatorio: {r['titulo']} (en {falta//60}h{falta%60:02d}min)"
    else: return f"Recordatorio: {r['titulo']} ({fecha_str} a las {hora_str})"

def _procesar_json_recordatorio(texto):
    m = re.search(r'\{.*"accion".*\}', texto, re.DOTALL)
    if not m: return None
    try: j = json.loads(m.group(0))
    except: return None
    accion = j.get("accion")
    if accion == "crear_recordatorio": return _ejecutar_recordatorio_json(j, texto)
    elif accion == "listar_recordatorios":
        if not recordatorios: return "No tienes recordatorios."
        lines = ["Tus recordatorios:"]
        for i, r in enumerate(sorted(recordatorios, key=lambda x: x["dispara"]), 1):
            d = datetime.fromisoformat(r["dispara"])
            lines.append(f"{i}. {r['titulo']} - {d.strftime('%d/%m %H:%M')} [{r['categoria']}]")
        return "\n".join(lines)
    elif accion == "borrar_recordatorio":
        idx, tit = j.get("id"), (j.get("titulo") or "").lower()
        for i, r in enumerate(recordatorios):
            if (idx and r["id"] == idx) or (tit and tit in r["titulo"].lower()):
                e = recordatorios.pop(i); _guardar_cal(); return f"Borrado: {e['titulo']}"
        return "No encontre ese recordatorio."
    elif accion == "pedir_aclaracion": return f"❓ {j.get('pregunta', 'Necesito mas detalles.')}"
    return None

# --- Memoria ---
historial = []

def recordar(mensaje, respuesta, topico=None):
    historial.append({"msg": mensaje, "resp": respuesta, "topico": topico, "ts": time.time()})
    while len(historial) > 12: historial.pop(0)

PALABRAS_CLIMA = ["tiempo","clima","temperatura","lluvia","calor","frio","soleado","nublado","paraguas","humedad","viento"]
PALABRAS_GAMING = ["juego","jugar","videojuego","consola","nintendo","playstation","xbox","steam","switch","ps5","ps4","gta","pokemon","zelda","rumor","filtracion","lanzamiento","review","analisis","fps","metacritic","ventas","ign","eurogamer"]
PALABRAS_RECORDATORIO = ["recordatorio","recuerda","recuerdame","avisame","avísame","alarma","notificame","cita","reunion","reunión","tarea","pendiente","plazo","vencimiento","sepe","labora"]
PALABRAS_GMAIL = ["email","correo","gmail","mensaje","bandeja","inbox","leer email","revisa email","mira el correo","borrador","responder email","prepara respuesta","importante","cuerpo","contenido","encabezamiento","cabecera","asunto","remitente","responde","responder","respondele","borra borrador","borrar borrador","lista borradores"]

def _detectar_topico(texto):
    baja = texto.lower()
    if any(w in baja for w in PALABRAS_RECORDATORIO): return "recordatorio"
    if any(w in baja for w in PALABRAS_GMAIL): return "gmail"
    if any(w in baja for w in PALABRAS_CLIMA):
        c = re.search(r'(?:en|de|para)\s+(\w+(?:\s+\w+)?)', texto, re.I)
        return f"clima {c.group(1).strip() if c else ''}"
    if any(w in baja for w in PALABRAS_GAMING): return "gaming"
    m = re.match(r'(?:que|qué|como|cómo|cuando|cuándo|donde|dónde|por que)\s+(.+)', baja)
    if m: return " ".join(m.group(1).split()[:4])
    return " ".join(baja.split()[:4])

def _reformular_consulta(mensaje):
    if not historial: return mensaje
    baja = mensaje.lower().strip()
    ult_top = (historial[-1].get("topico") or "") or _topico_previo()
    if any(p in baja for p in ["ahora sobre","ahora quiero","cambia","cambiar","otra cosa","diferente"]): return mensaje
    if ult_top.startswith("clima"):
        limpio = baja
        for p in ["tiempo en","tiempo de","tiempo para","clima en","clima de"]: limpio = re.sub(r'^y?\s*'+re.escape(p)+r'\s*','',limpio).strip()
        if limpio == baja: limpio = re.sub(r'^(?:y\s+|y\s*)?(?:en|de|para|del|de la)?\s*','',baja).strip()
        if limpio and len(limpio.split())<=2 and not any(w in limpio for w in ["tiempo","clima","que","como","cuando","donde"]): return f"tiempo en {limpio}"
    if baja.startswith("pero "): return mensaje

    # Si el tema anterior era gmail, asumir que cualquier referencia es sobre correos
    if ult_top and "gmail" in ult_top and not any(w in baja for w in PALABRAS_GMAIL):
        m = re.search(r'(?:el|la|del|al)\s*(\d+)', baja)
        if m:
            return f"cuerpo del {m.group(1)}"
        return f"correo {baja}"

    if baja.startswith(("y ","entonces ","tambien ","también ")):
        resto = re.sub(r'^(?:y|entonces|tambien|también)\s+','',baja)
        return f"{ult_top} {resto}" if ult_top else mensaje
    m = re.match(r'(?:y\s+)?(?:en|de|para)\s+(.+?)\s*\??$',baja)
    if m: return f"{ult_top} en {m.group(1)}" if ult_top else mensaje
    m = re.match(r'(?:el|la|los|las|del|de la|sus)\s+(.+)$',baja)
    if m and ult_top: return f"{ult_top} {m.group(1)}"
    if len(baja.split())<=4 and baja in ["dime mas","dime más","sigue","continua","continúa","más info","mas info"]:
        return f"{ult_top} mas informacion" if ult_top else mensaje
    return mensaje

def _topico_previo():
    for h in reversed(historial):
        if h.get("topico"): return h["topico"]
    return ""

def _extraer_ciudad(texto):
    m = re.search(r'(?:en|de|para)\s+(\w+(?:\s+\w+)?)',texto,re.I)
    return m.group(1).strip().lower() if m else ""

def _buscar_gaming(query):
    r = _ddg_html(query)
    if r: return r
    r = _ddg_html(f"{query} 2026")
    return r or ""

def _es_recordatorio(texto):
    baja = texto.lower()
    if any(w in baja for w in PALABRAS_RECORDATORIO): return True
    if re.search(r'(mañana|pasado mañana|el lunes|el martes|el miercoles|el jueves|el viernes|el sabado|el domingo|a las \d+|en \d+ (min|hora|dia|día|minuto))',baja):
        if any(w in baja for w in ["tengo","hay que","que hacer","cita","reunion","reunión","plazo"]): return True
    return False

def _es_gmail(texto):
    baja = texto.lower()
    return any(w in baja for w in PALABRAS_GMAIL)

def generar_respuesta(mensaje):
    hoy = datetime.now().strftime("%d/%m/%Y")
    consulta = _reformular_consulta(mensaje)

    # 1. Recordatorios
    if _es_recordatorio(consulta):
        sys_p = SYS_RECORDATORIO.format(hoy=hoy)
        msgs = [{"role":"system","content":sys_p}]
        for h in historial[-3:]:
            msgs.append({"role":"user","content":h["msg"]})
            msgs.append({"role":"assistant","content":h["resp"][:200]})
        msgs.append({"role":"user","content":mensaje})
        try:
            rta = ia_chat(msgs)
            if rta:
                resultado = _procesar_json_recordatorio(rta)
                if resultado:
                    recordar(mensaje, resultado, "recordatorio")
                    return resultado
        except: pass

    # 2. Gmail
    if _es_gmail(consulta):
        if not GMAIL_TOKEN_B64:
            return "Gmail no configurado."

        es_ultimo = "ultimo" in consulta or "último" in consulta
        es_leidos = "leido" in consulta or "leído" in consulta or "todos" in consulta

        # --- Listar borradores ---
        if "lista" in consulta and "borrador" in consulta:
            return _listar_borradores()

        # --- Borrar borrador ---
        if ("borra" in consulta or "elimina" in consulta) and "borrador" in consulta:
            m = re.search(r'(?:borrador|de)\s+(.+?)(?:\s*$)', consulta, re.I)
            if m: return _borrar_borrador(m.group(1).strip())
            return "Que borrador quieres borrar?"

        # --- Cuerpo de un email ---
        if "cuerpo" in consulta or "contenido" in consulta or "lee" in consulta or "leer" in consulta:
            eid = None
            m_num = re.search(r'(?:el|al)\s*(\d+)$', consulta)
            if m_num:
                eid = _email_por_numero(int(m_num.group(1)))
            if not eid:
                barra = re.search(r'/(.+?)(?:\s*$)', consulta)
                if barra:
                    term = barra.group(1).strip()
                    eid = _buscar_email_id(term)
                    if not eid: eid = _buscar_email_id(f"from:{term}")
                else:
                    m = re.search(r'(?:de|del)\s+(.+?)(?:\s*$)', consulta, re.I)
                    if m:
                        term = m.group(1).strip()
                        eid = _buscar_email_id(term)
                        if not eid: eid = _buscar_email_id(f"from:{term}")
            if eid: return _leer_cuerpo(eid)
            return _leer_inbox()

        # --- Responder (borrador respuesta) ---
        if "responde" in consulta or "responder" in consulta:
            eid, texto_resp, user_instruction = None, "", ""
            m_num = re.search(r'(?:al|el)\s*(\d+)', consulta)
            if m_num: eid = _email_por_numero(int(m_num.group(1)))
            if not eid:
                barra = re.search(r'/(.+?)(?:\s+diciendo|\s+que\s+|\s*$)', consulta)
                if barra: eid = _buscar_email_id(barra.group(1).strip())
            if not eid:
                m = re.search(r'(?:de|del|a)\s+(.+?)(?:\s+diciendo|\s+que\s+|\s*$)', consulta, re.I)
                if m: eid = _buscar_email_id(m.group(1).strip())
            m = re.search(r'(?:diciendo|que)\s+(.+?)(?:\s*$)', consulta, re.I)
            if m: texto_resp = m.group(1).strip()
            if not eid: return "A que email quieres responder?"

            if texto_resp:
                return _crear_borrador_respuesta(eid, texto_resp)

            # Si no dijo el texto exacto, leemos el correo y la IA genera respuesta
            cuerpo = _leer_cuerpo(eid)
            if cuerpo.startswith("Gmail no") or cuerpo.startswith("Error"):
                return f"No pude leer el correo: {cuerpo}"
            # Extraer instruccion de estilo (lo que dijo despues del numero sin "diciendo")
            resto = re.sub(r'^.*?(?:\b\d+\b)\s*', '', consulta, count=1).strip()
            user_instruction = f" ({resto})" if resto and resto not in consulta[:5] else ""
            msgs = [
                {"role": "system", "content": f"Eres RyuBot, asistente que redacta respuestas de email en español. Hoy es {hoy}. Responde SOLO con el texto del email, sin explicaciones."},
                {"role": "user", "content": f"Correo:\n{cuerpo}\n\nRedacta respuesta adecuada{user_instruction}."}
            ]
            try:
                generado = ia_chat(msgs)
                if generado:
                    resultado = _crear_borrador_respuesta(eid, generado)
                    return f"{resultado}\n\n{generado[:500]}"
            except: pass
            return "No pude generar la respuesta."

        # --- Borrador nuevo ---
        if "nuevo borrador" in consulta or "nuevo email" in consulta:
            return "Dime: para quien, asunto y mensaje."

        # --- Importantes ---
        if "importante" in consulta:
            imp = _buscar_importantes()
            if imp: return "Importantes:\n"+("\n".join(imp))
            return "No hay correos importantes nuevos."

        # --- Detectar fecha ---
        filtro_fecha = ""
        meses = {"enero":"01","febrero":"02","marzo":"03","abril":"04","mayo":"05","junio":"06",
                 "julio":"07","agosto":"08","septiembre":"09","octubre":"10","noviembre":"11","diciembre":"12"}
        m_fecha = re.search(r'(?:del?|dia)\s+(\d{1,2})\s*(?:de\s+)?(\w+)?\s*(?:de\s+)?(\d{4})?', consulta, re.I)
        if m_fecha:
            dia, mes_str, anio = m_fecha.group(1), m_fecha.group(2), m_fecha.group(3)
            mes = meses.get(mes_str.lower() if mes_str else "", "")
            if mes:
                if not anio: anio = datetime.now().strftime("%Y")
                filtro_fecha = f"after:{anio}/{mes}/{int(dia)-1} before:{anio}/{mes}/{int(dia)+1}"
                solo_no_leidos = False
        if "ayer" in consulta:
            ayer = datetime.now() - timedelta(days=1)
            filtro_fecha = f"after:{ayer.strftime('%Y/%m/%d')} before:{(ayer+timedelta(days=1)).strftime('%Y/%m/%d')}"
            solo_no_leidos = False
        if "hoy" in consulta and not filtro_fecha:
            hoy_dt = datetime.now()
            filtro_fecha = f"after:{hoy_dt.strftime('%Y/%m/%d')} before:{(hoy_dt+timedelta(days=1)).strftime('%Y/%m/%d')}"
            solo_no_leidos = False

        # --- Leer inbox (con filtro) ---
        max_r = 20 if filtro_fecha else (1 if es_ultimo else 5)
        filtro = filtro_fecha or ""
        # Detectar filtro adicional (remitente, asunto, /termino)
        palabras_fecha = {"hoy","ayer","mañana","pasado","semana","mes","año","dia","día"}
        barra = re.search(r'/(.+?)(?:\s*$)', consulta)
        if barra:
            term = barra.group(1).strip()
            filtro = f"{filtro} {term}" if filtro else term
            solo_no_leidos = False
        else:
            m = re.search(r'(?:de|del)\s+(.+?)(?:\s+y\s+|\s*$)', consulta, re.I)
            if m:
                t = m.group(1).strip().lower()
                if t not in palabras_fecha and "enero" not in t and not any(mm in t for mm in meses):
                    if t in consulta.lower():
                        filtro_extra = f"from:{m.group(1).strip()}"
                        filtro = f"{filtro} {filtro_extra}" if filtro else filtro_extra
            m = re.search(r'(?:sobre|acerca de)\s+(.+?)(?:\s*$)', consulta, re.I)
            if m and not filtro_fecha:
                filtro = m.group(1).strip()
            m = re.search(r'(?:asunto|tema)\s+(.+?)(?:\s*$)', consulta, re.I)
            if m and not filtro:
                filtro = f"subject:{m.group(1).strip()}"
        return _leer_inbox(max_r=max_r, filtro=filtro.strip(), solo_no_leidos=solo_no_leidos)

    # 3. Clima / Gaming / Normal
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

    msgs = [{"role":"system","content":sys_p}]
    for h in historial[-4:]:
        msgs.append({"role":"user","content":h["msg"]})
        msgs.append({"role":"assistant","content":h["resp"][:200]})
    prompt = mensaje
    if ctx: prompt += f"\n[Info: {ctx}]"
    msgs.append({"role":"user","content":prompt})

    try:
        rta = ia_chat(msgs)
        if not rta: raise ValueError
        topico = _detectar_topico(consulta)
        recordar(mensaje, rta, topico)
        return rta[:2000]
    except Exception as e:
        log.warning(f"IA fallo: {e}")
        rta = "Lo siento, no pude procesar eso."
        recordar(mensaje, rta)
        return rta

# --- Hilo recordatorios ---
def _revisar_recordatorios():
    while True:
        try:
            _cargar_cal()
            ahora = datetime.now()
            for r in [r for r in recordatorios if datetime.fromisoformat(r["dispara"])<=ahora]:
                http.post(f"{API}/sendMessage",json={"chat_id":CHAT_ID,"text":f"⏰ <b>RECORDATORIO:</b> {_h(r['titulo'])} [{r['categoria']}]","parse_mode":"HTML"})


                recordatorios.remove(r); _guardar_cal()
        except: pass
        time.sleep(30)
threading.Thread(target=_revisar_recordatorios,daemon=True).start()

# --- Hilo Gmail importantes ---
def _revisar_gmail():
    while True:
        if GMAIL_TOKEN_B64:
            try:
                imp = _buscar_importantes()
                if imp:
                    for item in imp:
                        http.post(f"{API}/sendMessage",json={"chat_id":CHAT_ID,"text":f"📬 <b>IMPORTANTE:</b> {_h(item)}","parse_mode":"HTML"})
            except: pass
        time.sleep(300)
threading.Thread(target=_revisar_gmail,daemon=True).start()

# --- Polling ---
def poll():
    global last_update
    log.info("Bot iniciado.")
    while True:
        try:
            r = http.get(f"{API}/getUpdates",params={"offset":last_update+1,"timeout":30})
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
                                # Limpiar ** y separar listas
                                resp = resp.replace("**", "")
                                resp = re.sub(r'\n(\d+[\.\)])', r'\n\n\1', resp)
                                resp = resp.replace("\n\n\n", "\n\n")
                                txt = resp if "<b>" in resp or "<i>" in resp else _h(resp)
                                http.post(f"{API}/sendMessage",json={"chat_id":CHAT_ID,"text":txt,"parse_mode":"HTML"})
                        except Exception as e:
                            log.error(f"Resp error: {e}")
        except Exception as e:
            log.error(f"Poll error: {e}")
            time.sleep(3)

if __name__ == "__main__":
    poll()