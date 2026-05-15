from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse
from pydantic import BaseModel
import mysql.connector
import threading
import queue
import os
from email.message import EmailMessage

app = FastAPI()

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

# ════════════════════════════════════════════════════════════════════
#  CONFIGURACIÓN — Lee de variables de entorno si existen (nube)
#  En local usa los valores por defecto
# ════════════════════════════════════════════════════════════════════
BREVO_API_KEY  = os.getenv("BREVO_API_KEY",  "")
EMAIL_EMISOR   = os.getenv("EMAIL_EMISOR",   "mariapizbv@gmail.com")

DB_HOST     = os.getenv("DB_HOST",     "localhost")
DB_USER     = os.getenv("DB_USER",     "root")
DB_PASSWORD = os.getenv("DB_PASSWORD", "maria123")
DB_NAME     = os.getenv("DB_NAME",     "telecola_db")

@app.get("/")
def root(): return FileResponse("index.html")

@app.get("/index.html")
def index_html(): return FileResponse("index.html")

@app.get("/admin")
def admin(): return FileResponse("admin.html")

@app.get("/medicamentos.html")
def medicamentos_html(): return FileResponse("medicamentos.html")

@app.get("/medicamentos")
def medicamentos(): return FileResponse("medicamentos.html")

@app.get("/admin.html")
def admin_html(): return FileResponse("admin.html")

@app.get("/script.js")
def script_js(): return FileResponse("script.js")

@app.get("/api.js")
def api_js(): return FileResponse("api.js")

@app.get("/styles.css")
def styles_css(): return FileResponse("styles.css")

# Lock para evitar condiciones de carrera cuando 30 personas
# solicitan turno al mismo tiempo
_turno_lock = threading.Lock()

# Cola de correos — un hilo dedicado los envía en orden sin bloquear
_mail_queue: queue.Queue = queue.Queue()


def _worker_correos():
    """Hilo permanente que procesa la cola de correos via Resend."""
    while True:
        try:
            item = _mail_queue.get()
            if item is None:
                break
            destinatario, asunto, cuerpo = item

            lineas_html = "".join(
                f'<p style="margin:0 0 12px;color:#1a1a1a;line-height:1.6;">{line}</p>'
                for line in cuerpo.strip().split("\n") if line.strip()
            )

            html = f"""<html><body style="margin:0;padding:0;background:#eef4f0;font-family:Arial,Helvetica,sans-serif;">
<table width="100%" cellpadding="0" cellspacing="0" style="background:#eef4f0;padding:28px 0"><tr><td align="center">
<table width="500" cellpadding="0" cellspacing="0" style="background:#ffffff;border-radius:14px;overflow:hidden;border:1px solid #d4e8dd">
  <tr><td style="background:#0b3d2e;padding:22px 28px;text-align:center">
    <span style="font-family:Arial,Helvetica,sans-serif;font-size:26px;font-weight:900;color:#ffffff;vertical-align:middle;letter-spacing:-0.5px">TELE<span style="color:#00c98a">COLA</span></span>
    <div style="font-family:Arial,Helvetica,sans-serif;font-size:9px;letter-spacing:2px;color:rgba(255,255,255,0.45);text-transform:uppercase;margin-top:6px">FILAS VIRTUALES &nbsp;&middot;&nbsp; BOGOT&Aacute;</div>
  </td></tr>
  <tr><td style="background:#00c98a;height:3px;font-size:0">&nbsp;</td></tr>
  <tr><td style="padding:24px 28px">{lineas_html}</td></tr>
  <tr><td style="padding:14px 28px 20px;text-align:center;background:#f4fbf7">
    <p style="margin:0;font-size:10px;color:#7a9e8b;font-family:Arial,sans-serif">
      Mensaje autom&aacute;tico &mdash; no respondas este correo<br>
      <strong style="color:#0b3d2e">TELECOLA</strong> &nbsp;&middot;&nbsp; Farmacia &nbsp;&middot;&nbsp; Bogot&aacute;, Colombia
    </p>
  </td></tr>
</table>
</td></tr></table>
</body></html>"""

            import urllib.request, json as _json
            payload = _json.dumps({
                "sender": {"name": "TELECOLA Farmacia", "email": EMAIL_EMISOR},
                "to": [{"email": destinatario}],
                "subject": asunto,
                "htmlContent": html
            }).encode()
            req = urllib.request.Request(
                "https://api.brevo.com/v3/smtp/email",
                data=payload,
                headers={
                    "api-key": BREVO_API_KEY,
                    "Content-Type": "application/json"
                },
                method="POST"
            )
            with urllib.request.urlopen(req, timeout=15) as resp:
                print(f"✅ Correo Brevo → {destinatario} ({resp.status})")

        except Exception as e:
            print(f"❌ Error correo Resend: {type(e).__name__}: {e}")
        finally:
            _mail_queue.task_done()

# Arrancar el worker al iniciar
_mail_thread = threading.Thread(target=_worker_correos, daemon=True)
_mail_thread.start()


def enviar_correo_async(destinatario: str, asunto: str, cuerpo: str):
    """Encola el correo — retorna inmediatamente, el worker lo envía."""
    _mail_queue.put((destinatario, asunto, cuerpo))

# ─── BASE DE DATOS ───────────────────────────────────────────────────
def get_db():
    return mysql.connector.connect(
        host=DB_HOST,
        user=DB_USER,
        password=DB_PASSWORD,
        database=DB_NAME
    )

class TurnoRequest(BaseModel):
    documento: str


# ════════════════════════════════════════════════════════════════════
#  MEDICAMENTOS
# ════════════════════════════════════════════════════════════════════
@app.get("/api/medicamentos")
def listar_medicamentos():
    """Todos los medicamentos (con y sin stock) para el catálogo."""
    conn = get_db()
    cursor = conn.cursor(dictionary=True)
    cursor.execute(
        "SELECT id, nombre, concentracion, stock, disponible FROM medicamentos ORDER BY nombre"
    )
    meds = cursor.fetchall()
    conn.close()
    return meds


# ════════════════════════════════════════════════════════════════════
#  TURNOS — USUARIO
# ════════════════════════════════════════════════════════════════════
@app.post("/api/turnos/solicitar")
def solicitar_turno(req: TurnoRequest):
    # Lock garantiza que solo una persona a la vez pase por
    # la sección crítica (verificar duplicado + insertar turno)
    with _turno_lock:
        conn = get_db()
        cursor = conn.cursor(dictionary=True)

        # 1. Validar usuario
        cursor.execute(
            "SELECT tipo_usuario, correo, nombre, telefono, medicamento_id FROM usuarios WHERE documento = %s",
            (req.documento,)
        )
        user = cursor.fetchone()
        if not user:
            conn.close()
            raise HTTPException(status_code=404, detail="Cédula no registrada en el sistema.")
        if not user.get("medicamento_id"):
            conn.close()
            raise HTTPException(status_code=400, detail="No tienes un medicamento asignado. Consulta con el administrador.")

        # 2. Verificar stock disponible
        cursor.execute(
            "SELECT stock FROM medicamentos WHERE id = %s AND disponible = 1",
            (user["medicamento_id"],)
        )
        med_stock = cursor.fetchone()
        if not med_stock or med_stock["stock"] <= 0:
            conn.close()
            raise HTTPException(status_code=400, detail="Tu medicamento no tiene stock disponible hoy. Acércate a la farmacia para más información.")

        # 3. Sin turno duplicado hoy
        cursor.execute(
            """SELECT id FROM turnos
               WHERE documento_usuario = %s
                 AND estado IN ('en_espera','atendiendo')
                 AND DATE(fecha_creacion) = CURDATE()""",
            (req.documento,)
        )
        if cursor.fetchone():
            conn.close()
            raise HTTPException(status_code=400, detail="Ya tienes un turno activo hoy.")

        # 4. Generar código (P=prioritario, A=general)
        is_prio = user["tipo_usuario"] in ("mayor", "especial")
        prefijo = "P" if is_prio else "A"
        cursor.execute("SELECT COUNT(*) AS total FROM turnos WHERE DATE(fecha_creacion) = CURDATE()")
        num    = cursor.fetchone()["total"] + 1
        codigo = f"{prefijo}-{str(num).zfill(3)}"

        # 5. Insertar turno
        cursor.execute(
            "INSERT INTO turnos (codigo, documento_usuario, medicamento_id) VALUES (%s, %s, %s)",
            (codigo, req.documento, user["medicamento_id"])
        )
        turno_id = cursor.lastrowid

        # 6. Descontar stock al solicitar el turno
        cursor.execute(
            "UPDATE medicamentos SET stock = stock - 1 WHERE id = %s AND stock > 0",
            (user["medicamento_id"],)
        )

        # 7. Datos del medicamento para el correo
        cursor.execute(
            "SELECT nombre, concentracion FROM medicamentos WHERE id = %s",
            (user["medicamento_id"],)
        )
        med = cursor.fetchone()
        conn.commit()
        conn.close()

    # 8. Correo de confirmación (fuera del lock, en hilo separado)
    tipo_txt = "Prioritario ⭐" if is_prio else "General"
    enviar_correo_async(
        user["correo"],
        f"✅ Turno {codigo} registrado — TELECOLA",
        f"""Hola {user['nombre']},

Tu turno ha sido registrado exitosamente.

🎫 Número de turno : {codigo}
💊 Medicamento     : {med['nombre']} {med['concentracion']}
📋 Tipo            : {tipo_txt}

Te avisaremos cuando sea casi tu momento.
No necesitas hacer fila — espera nuestra notificación.

— Sistema TELECOLA"""
    )

    return {
        "id": turno_id,
        "codigo_turno": codigo,
        "is_prio": is_prio,
        "medicamento": f"{med['nombre']} {med['concentracion']}"
    }


@app.get("/api/turnos/estado/{turno_id}")
def estado_turno(turno_id: int):
    conn = get_db()
    cursor = conn.cursor(dictionary=True)
    cursor.execute("SELECT id, codigo, estado FROM turnos WHERE id = %s", (turno_id,))
    turno = cursor.fetchone()
    if not turno:
        conn.close()
        raise HTTPException(status_code=404, detail="Turno no encontrado.")
    posicion = 0
    if turno["estado"] == "en_espera":
        cursor.execute(
            """SELECT COUNT(*) AS pos FROM turnos
               WHERE estado='en_espera' AND DATE(fecha_creacion)=CURDATE() AND id<=%s""",
            (turno_id,)
        )
        posicion = cursor.fetchone()["pos"]
    conn.close()
    return {"id":turno["id"],"codigo":turno["codigo"],"estado":turno["estado"],"posicion":posicion}


@app.get("/api/turnos/consultar/{documento}")
def consultar_turno_por_doc(documento: str):
    conn = get_db()
    cursor = conn.cursor(dictionary=True)
    cursor.execute(
        """SELECT t.id,t.codigo,t.estado,m.nombre AS medicamento,m.concentracion
           FROM turnos t JOIN medicamentos m ON t.medicamento_id=m.id
           WHERE t.documento_usuario=%s AND t.estado IN ('en_espera','atendiendo')
             AND DATE(t.fecha_creacion)=CURDATE()
           ORDER BY t.fecha_creacion DESC LIMIT 1""",
        (documento,)
    )
    turno = cursor.fetchone()
    if not turno:
        conn.close()
        raise HTTPException(status_code=404, detail="No tienes un turno activo hoy.")
    posicion = 0
    if turno["estado"] == "en_espera":
        cursor.execute(
            """SELECT COUNT(*) AS pos FROM turnos
               WHERE estado='en_espera' AND DATE(fecha_creacion)=CURDATE() AND id<=%s""",
            (turno["id"],)
        )
        posicion = cursor.fetchone()["pos"]
    conn.close()
    return {"id":turno["id"],"codigo":turno["codigo"],"estado":turno["estado"],
            "medicamento":f"{turno['medicamento']} {turno['concentracion']}","posicion":posicion}


# ════════════════════════════════════════════════════════════════════
#  ADMIN
# ════════════════════════════════════════════════════════════════════
@app.get("/api/admin/turnos")
def listar_turnos_admin():
    conn = get_db()
    cursor = conn.cursor(dictionary=True)
    cursor.execute(
        """SELECT t.id,t.codigo,t.documento_usuario AS documento,t.estado,
                  u.telefono,u.tipo_usuario,
                  m.nombre AS medicamento,m.concentracion
           FROM turnos t
           JOIN usuarios u ON t.documento_usuario=u.documento
           JOIN medicamentos m ON t.medicamento_id=m.id
           WHERE t.estado IN ('en_espera','atendiendo')
             AND DATE(t.fecha_creacion)=CURDATE()
           ORDER BY CASE t.estado WHEN 'atendiendo' THEN 0 ELSE 1 END,
                    CASE WHEN t.codigo LIKE 'P-%' THEN 0 ELSE 1 END,
                    t.id ASC"""
    )
    turnos = cursor.fetchall()
    conn.close()
    return turnos


@app.put("/api/admin/turnos/{turno_id}/atender")
def atender_turno(turno_id: int):
    conn = get_db()
    cursor = conn.cursor(dictionary=True)
    cursor.execute(
        """SELECT u.correo,u.nombre,t.codigo
           FROM turnos t JOIN usuarios u ON t.documento_usuario=u.documento
           WHERE t.id=%s""",
        (turno_id,)
    )
    datos = cursor.fetchone()
    if not datos:
        conn.close()
        raise HTTPException(status_code=404, detail="Turno no encontrado.")

    cursor.execute("UPDATE turnos SET estado='atendiendo' WHERE id=%s", (turno_id,))

    cursor.execute(
        """SELECT t.id,u.correo,u.nombre,t.codigo AS cod
           FROM turnos t JOIN usuarios u ON t.documento_usuario=u.documento
           WHERE t.estado='en_espera' AND DATE(t.fecha_creacion)=CURDATE()
           ORDER BY t.id ASC LIMIT 1"""
    )
    siguiente = cursor.fetchone()
    conn.commit()
    conn.close()

    enviar_correo_async(
        datos["correo"],
        f"📢 ¡Tu turno {datos['codigo']} está siendo atendido! — TELECOLA",
        f"Hola {datos['nombre']},\n\nTu turno {datos['codigo']} ha sido llamado.\nPor favor acércate a la ventanilla ahora.\n\n— Sistema TELECOLA"
    )
    if siguiente:
        enviar_correo_async(
            siguiente["correo"],
            f"⏰ Prepárate — tu turno {siguiente['cod']} es el siguiente — TELECOLA",
            f"Hola {siguiente['nombre']},\n\nEres el siguiente en la cola.\nEn aproximadamente 5 minutos será tu turno {siguiente['cod']}.\nPor favor estate listo cerca de la ventanilla.\n\n— Sistema TELECOLA"
        )
    return {"status":"ok","mensaje":"Turno atendido y correos enviados."}


@app.put("/api/admin/turnos/{turno_id}/completar")
def completar_turno(turno_id: int):
    conn = get_db()
    cursor = conn.cursor(dictionary=True)
    cursor.execute("SELECT id FROM turnos WHERE id=%s", (turno_id,))
    if not cursor.fetchone():
        conn.close()
        raise HTTPException(status_code=404, detail="Turno no encontrado.")
    cursor.execute("UPDATE turnos SET estado='completado' WHERE id=%s", (turno_id,))
    conn.commit()
    conn.close()
    return {"status":"ok"}


@app.delete("/api/admin/turnos/{turno_id}")
def cancelar_turno(turno_id: int):
    conn = get_db()
    cursor = conn.cursor(dictionary=True)
    cursor.execute("SELECT medicamento_id FROM turnos WHERE id=%s AND estado IN ('en_espera','atendiendo')", (turno_id,))
    turno = cursor.fetchone()
    if turno:
        cursor.execute("UPDATE medicamentos SET stock=stock+1 WHERE id=%s", (turno["medicamento_id"],))
    cursor.execute("UPDATE turnos SET estado='cancelado' WHERE id=%s", (turno_id,))
    conn.commit()
    conn.close()
    return {"status":"ok"}
