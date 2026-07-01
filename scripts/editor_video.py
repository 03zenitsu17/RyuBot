import json, os, sys, tempfile, asyncio
from pathlib import Path

import moviepy as mp
import edge_tts
from faster_whisper import WhisperModel

FFMPEG_BIN = r"C:\Users\miroi\AppData\Local\Python\pythoncore-3.14-64\Lib\site-packages\imageio_ffmpeg\binaries\ffmpeg-win-x86_64-v7.1.exe"
os.environ["IMAGEIO_FFMPEG_EXE"] = FFMPEG_BIN

OUTPUT_DIR = Path.home() / "Videos" / "oficialRyu_edits"
OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

modelo_whisper = None

def _get_whisper():
    global modelo_whisper
    if modelo_whisper is None:
        modelo_whisper = WhisperModel("base", device="cpu", compute_type="int8")
    return modelo_whisper

def _path(ruta):
    p = Path(ruta)
    if not p.is_absolute():
        p = Path.cwd() / ruta
    if not p.exists():
        raise FileNotFoundError(f"No existe: {p}")
    return str(p)

def _out(nombre):
    return str(OUTPUT_DIR / nombre)

def cortar_video(video, inicio, fin, salida=None):
    v = mp.VideoFileClip(_path(video))
    clip = v.subclipped(inicio, fin)
    salida = salida or _out(f"cortado_{Path(video).stem}.mp4")
    clip.write_videofile(salida, ffmpeg_params=["-ffmpeg", FFMPEG_BIN])
    v.close()
    return salida

def unir_videos(videos, salida=None):
    clips = [mp.VideoFileClip(_path(v)) for v in videos]
    final = mp.concatenate_videoclips(clips)
    salida = salida or _out("union.mp4")
    final.write_videofile(salida, ffmpeg_params=["-ffmpeg", FFMPEG_BIN])
    for c in clips:
        c.close()
    return salida

def añadir_audio(video, audio, volumen=1.0, salida=None):
    v = mp.VideoFileClip(_path(video))
    a = mp.AudioFileClip(_path(audio)).with_effects([mp.vfx.MultiplyVolume(volumen)])
    if a.duration > v.duration:
        a = a.subclipped(0, v.duration)
    v = v.with_audio(a)
    salida = salida or _out(f"con_audio_{Path(video).stem}.mp4")
    v.write_videofile(salida, ffmpeg_params=["-ffmpeg", FFMPEG_BIN])
    v.close()
    return salida

def cambiar_velocidad(video, factor, salida=None):
    v = mp.VideoFileClip(_path(video))
    clip = v.with_effects([mp.vfx.MultiplySpeed(factor)])
    salida = salida or _out(f"vel_{factor}x_{Path(video).stem}.mp4")
    clip.write_videofile(salida, ffmpeg_params=["-ffmpeg", FFMPEG_BIN])
    v.close()
    return salida

def redimensionar(video, ancho=None, alto=None, salida=None):
    v = mp.VideoFileClip(_path(video))
    if ancho and alto:
        clip = v.resized((ancho, alto))
    elif ancho:
        clip = v.resized(width=ancho)
    else:
        clip = v.resized(height=alto)
    salida = salida or _out(f"redim_{Path(video).stem}.mp4")
    clip.write_videofile(salida, ffmpeg_params=["-ffmpeg", FFMPEG_BIN])
    v.close()
    return salida

async def texto_a_voz(texto, voz="es-ES-AlvaroNeural", salida=None):
    salida = salida or _out("voz_ai.mp3")
    communicate = edge_tts.Communicate(texto, voz)
    await communicate.save(salida)
    return salida

def listar_voces():
    return asyncio.run(edge_tts.list_voices())

def generar_subtitulos(video, idioma="es"):
    v = mp.VideoFileClip(_path(video))
    audio_tmp = tempfile.NamedTemporaryFile(suffix=".wav", delete=False)
    audio_tmp.close()
    v.audio.write_audiofile(audio_tmp.name, ffmpeg_params=["-ffmpeg", FFMPEG_BIN])
    v.close()
    whisper = _get_whisper()
    segments, info = whisper.transcribe(audio_tmp.name, language=idioma)
    srt_path = _out(f"subtitulos_{Path(video).stem}.srt")
    with open(srt_path, "w", encoding="utf-8") as f:
        for i, seg in enumerate(segments, 1):
            start = seg.start
            end = seg.end
            def ts(s):
                h = int(s // 3600)
                m = int((s % 3600) // 60)
                seg_s = s % 60
                return f"{h:02d}:{m:02d}:{seg_s:06.3f}".replace(".", ",")
            f.write(f"{i}\n{ts(start)} --> {ts(end)}\n{seg.text.strip()}\n\n")
    os.unlink(audio_tmp.name)
    return srt_path

def quemar_subtitulos(video, srt=None, salida=None):
    from moviepy import TextClip, CompositeVideoClip
    v = mp.VideoFileClip(_path(video))
    if srt is None:
        srt = generar_subtitulos(video)
    txt_clips = []
    with open(srt, encoding="utf-8") as f:
        lines = f.read().strip().split("\n\n")
    for block in lines:
        parts = block.split("\n")
        if len(parts) < 3:
            continue
        times = parts[1].split(" --> ")
        def to_s(t):
            t = t.replace(",", ".")
            h, m, s = t.split(":")
            return int(h) * 3600 + int(m) * 60 + float(s)
        t_start, t_end = to_s(times[0]), to_s(times[1])
        texto = "\n".join(parts[2:])
        txt = (mp.TextClip(text=texto, font="Arial", font_size=28, color="white",
                           stroke_color="black", stroke_width=1.5, method="label")
               .with_start(t_start).with_duration(t_end - t_start)
               .with_position(("center", "bottom")))
        txt_clips.append(txt)
    final = CompositeVideoClip([v, *txt_clips])
    salida = salida or _out(f"subs_{Path(video).stem}.mp4")
    final.write_videofile(salida, ffmpeg_params=["-ffmpeg", FFMPEG_BIN])
    v.close()
    return salida

def overlay_texto(video, texto, posicion="bottom", tamano=28, salida=None):
    v = mp.VideoFileClip(_path(video))
    txt = (mp.TextClip(text=texto, font="Arial", font_size=tamano, color="white",
                       stroke_color="black", stroke_width=1.5, method="label")
           .with_duration(v.duration).with_position(("center", posicion)))
    final = mp.CompositeVideoClip([v, txt])
    salida = salida or _out(f"texto_{Path(video).stem}.mp4")
    final.write_videofile(salida, ffmpeg_params=["-ffmpeg", FFMPEG_BIN])
    v.close()
    return salida

def extraer_audio(video, salida=None):
    v = mp.VideoFileClip(_path(video))
    salida = salida or _out(f"audio_{Path(video).stem}.mp3")
    v.audio.write_audiofile(salida, ffmpeg_params=["-ffmpeg", FFMPEG_BIN])
    v.close()
    return salida

def extraer_fotogramas(video, intervalo=5, max_fotos=20, salida_dir=None):
    v = mp.VideoFileClip(_path(video))
    dir_out = Path(salida_dir or _out(f"fotogramas_{Path(video).stem}"))
    dir_out.mkdir(parents=True, exist_ok=True)
    duracion = v.duration
    fotos = []
    t = 0
    while t < duracion and len(fotos) < max_fotos:
        salida = str(dir_out / f"fotograma_{int(t):04d}.jpg")
        frame = v.to_image(t)
        frame.save(salida, quality=85)
        fotos.append({"tiempo": t, "ruta": salida})
        t += intervalo
    v.close()
    return json.dumps({"total": len(fotos), "carpeta": str(dir_out), "fotogramas": fotos}, ensure_ascii=False)

if __name__ == "__main__":
    comando = sys.argv[1] if len(sys.argv) > 1 else "help"
    if comando == "help":
        print(json.dumps({
            "funciones": [
                {"nombre": "cortar_video", "params": ["video", "inicio", "fin", "salida?"], "desc": "Corta un video desde inicio a fin (segundos)"},
                {"nombre": "unir_videos", "params": ["videos[]", "salida?"], "desc": "Concatena varios videos"},
                {"nombre": "anadir_audio", "params": ["video", "audio", "volumen?", "salida?"], "desc": "Añade pista de audio a un video"},
                {"nombre": "cambiar_velocidad", "params": ["video", "factor", "salida?"], "desc": "Cambia velocidad (2=2x, 0.5=mitad)"},
                {"nombre": "redimensionar", "params": ["video", "ancho?", "alto?", "salida?"], "desc": "Redimensiona video"},
                {"nombre": "texto_a_voz", "params": ["texto", "voz?", "salida?"], "desc": "Genera audio AI desde texto (edge-tts)"},
                {"nombre": "listar_voces", "params": [], "desc": "Lista voces disponibles para texto_a_voz"},
                {"nombre": "generar_subtitulos", "params": ["video", "idioma?"], "desc": "Genera archivo SRT desde el audio del video"},
                {"nombre": "quemar_subtitulos", "params": ["video", "srt?", "salida?"], "desc": "Quema subtitulos SRT en el video"},
                {"nombre": "overlay_texto", "params": ["video", "texto", "posicion?", "tamano?", "salida?"], "desc": "Añade texto permanente sobre el video"},
                {"nombre": "extraer_audio", "params": ["video", "salida?"], "desc": "Extrae el audio de un video"},
                {"nombre": "extraer_fotogramas", "params": ["video", "intervalo?", "max_fotos?", "salida_dir?"], "desc": "Extrae fotogramas del video como imagenes JPG"},
            ]
        }, ensure_ascii=False))
    else:
        fn = globals().get(comando)
        if not fn:
            print(json.dumps({"error": f"Comando desconocido: {comando}"}))
            sys.exit(1)
        args = sys.argv[2:]
        try:
            if asyncio.iscoroutinefunction(fn):
                resultado = asyncio.run(fn(*args))
            else:
                resultado = fn(*args)
            print(json.dumps({"ok": True, "resultado": resultado}, ensure_ascii=False))
        except Exception as e:
            print(json.dumps({"ok": False, "error": str(e)}, ensure_ascii=False))
            sys.exit(1)
