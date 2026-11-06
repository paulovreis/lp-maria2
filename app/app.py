"""
Landing page editável — Hélder Sorteios
Flask + SQLite. Todo o conteúdo (textos, imagens, cores, links, carrossel)
fica no banco e é editado em /admin. Salvou, vale na hora para todo mundo.
"""
import hmac
import os
import re
import secrets
import sqlite3
import threading
import time
import uuid
from datetime import timedelta
from functools import wraps

from flask import (
    Flask, g, jsonify, redirect, render_template, request,
    send_from_directory, session, url_for,
)
from werkzeug.middleware.proxy_fix import ProxyFix

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
DATA_DIR = os.environ.get("DATA_DIR", os.path.join(BASE_DIR, "data"))
DB_PATH = os.path.join(DATA_DIR, "lp.sqlite3")
UPLOAD_DIR = os.path.join(DATA_DIR, "uploads")
ALLOWED_EXT = {"png", "jpg", "jpeg", "webp", "gif"}
MAX_SLIDES = 15

app = Flask(__name__)
app.config.update(
    SECRET_KEY=os.environ.get("SECRET_KEY") or secrets.token_hex(32),
    MAX_CONTENT_LENGTH=8 * 1024 * 1024,  # 8 MB por upload
    SESSION_COOKIE_HTTPONLY=True,
    SESSION_COOKIE_SAMESITE="Lax",
    SESSION_COOKIE_SECURE=os.environ.get("SESSION_COOKIE_SECURE", "0") == "1",
    PERMANENT_SESSION_LIFETIME=timedelta(hours=12),
    JSON_AS_ASCII=False,
)
# Atrás do proxy do Easypanel (Traefik): confia nos cabeçalhos X-Forwarded-*
# para enxergar o IP real do visitante e o esquema https.
if os.environ.get("BEHIND_PROXY", "1") == "1":
    app.wsgi_app = ProxyFix(app.wsgi_app, x_for=1, x_proto=1, x_host=1)

ADMIN_PASSWORD = os.environ.get("ADMIN_PASSWORD", "")

# --------------------------------------------------------------------------
# Conteúdo padrão (chaves novas entram sozinhas; edições existentes não mudam)
# --------------------------------------------------------------------------
DEFAULT_CONTENT = {
    # Página / SEO
    "page_title": "Hélder Sorteios | Concorra a um Golf GTI Stage 2",
    "meta_description": "Concorra a um Golf GTI Stage 2 com a Hélder Sorteios.",
    "favicon_image": "/static/img/logo.png",
    "head_code": "",
    # Logo
    "show_logo": "0",
    "logo_image": "/static/img/logo.png",
    "logo_alt": "HS Hélder Sorteios",
    # Topo
    "hero_title": "Golf GTI",
    "hero_title_accent": "STAGE 2",
    "hero_accent_image": "/static/img/stage2.png",
    "slide_interval": "5",
    # Botão
    "cta_text": "Clique aqui",
    "cta_link": "https://helderporto.com/r/golfgtinov26?utm_source=ADS&ref=6b54dc81-fc51-4163-80ca-298aa47d2af7",
    "cta_new_tab": "1",
    "final_text": "Clique no botão",
    # Rodapé
    "footer_text": "© Hélder Sorteios. Todos os direitos reservados.",
    "footer_link_text": "",
    "footer_link": "",
    # Cores
    "color_black": "#000000",
    "color_green": "#6ECE30",
    "color_white": "#FFFFFF",
    "color_neon": "#39FF14",
}

DEFAULT_SLIDES = [
    "/static/img/premio/golf-frente.jpg",
    "/static/img/premio/golf-lateral.jpg",
    "/static/img/premio/golf-painel.jpg",
    "/static/img/premio/golf-bancos.jpg",
    "/static/img/premio/golf-banco-traseiro.jpg",
]

COLOR_KEYS = {"color_black", "color_green", "color_white", "color_neon"}
IMAGE_KEYS = {"logo_image", "hero_accent_image", "favicon_image"}  # podem ficar vazias
LINK_KEYS = {"cta_link", "footer_link"}                           # podem ficar vazios
BOOL_KEYS = {"show_logo", "cta_new_tab"}
INT_RANGES = {"slide_interval": (2, 30)}
CODE_KEYS = {"head_code"}
TEXT_LIMITS = {
    "page_title": 160, "meta_description": 300, "logo_alt": 160,
    "hero_title": 60, "hero_title_accent": 60, "cta_text": 60,
    "final_text": 200, "footer_text": 300, "footer_link_text": 80,
}
assert set(TEXT_LIMITS) | COLOR_KEYS | IMAGE_KEYS | LINK_KEYS | BOOL_KEYS | set(INT_RANGES) | CODE_KEYS == set(DEFAULT_CONTENT)

HEX_RE = re.compile(r"^#[0-9a-fA-F]{6}$")
SAFE_LINK_RE = re.compile(r"^(https?://|/|#|mailto:|tel:)", re.IGNORECASE)


def is_safe_image(value) -> bool:
    return isinstance(value, str) and (
        value.startswith("/uploads/") or value.startswith("/static/img/")
        or value.startswith("https://")
    ) and len(value) <= 500 and not re.search(r'[\s"<>\\]', value)


# --------------------------------------------------------------------------
# Banco de dados
# --------------------------------------------------------------------------
def get_db():
    if "db" not in g:
        g.db = sqlite3.connect(DB_PATH, timeout=10)
        g.db.row_factory = sqlite3.Row
    return g.db


@app.teardown_appcontext
def close_db(_exc):
    db = g.pop("db", None)
    if db is not None:
        db.close()


def init_db():
    os.makedirs(UPLOAD_DIR, exist_ok=True)
    db = sqlite3.connect(DB_PATH)
    db.execute("PRAGMA journal_mode=WAL")
    db.executescript(
        """
        CREATE TABLE IF NOT EXISTS content (
            key        TEXT PRIMARY KEY,
            value      TEXT NOT NULL,
            updated_at TEXT NOT NULL DEFAULT (datetime('now'))
        );
        CREATE TABLE IF NOT EXISTS slides (
            id         INTEGER PRIMARY KEY AUTOINCREMENT,
            image      TEXT NOT NULL,
            position   INTEGER NOT NULL DEFAULT 0,
            updated_at TEXT NOT NULL DEFAULT (datetime('now'))
        );
        CREATE TABLE IF NOT EXISTS meta (
            key   TEXT PRIMARY KEY,
            value TEXT NOT NULL
        );
        """
    )
    db.executemany(
        "INSERT OR IGNORE INTO content (key, value) VALUES (?, ?)",
        DEFAULT_CONTENT.items(),
    )
    # Fotos iniciais só entram na primeira vez; depois o admin manda
    # (inclusive deixar o carrossel vazio).
    if not db.execute("SELECT 1 FROM meta WHERE key = 'slides_seeded'").fetchone():
        db.executemany(
            "INSERT INTO slides (image, position) VALUES (?, ?)",
            [(img, pos) for pos, img in enumerate(DEFAULT_SLIDES)],
        )
        db.execute("INSERT INTO meta (key, value) VALUES ('slides_seeded', '1')")
    db.commit()
    db.close()


def load_content():
    rows = get_db().execute("SELECT key, value FROM content").fetchall()
    data = dict(DEFAULT_CONTENT)
    data.update({r["key"]: r["value"] for r in rows if r["key"] in DEFAULT_CONTENT})
    return data


def load_slides():
    rows = get_db().execute("SELECT id, image FROM slides ORDER BY position, id").fetchall()
    return [dict(r) for r in rows]


# --------------------------------------------------------------------------
# Autenticação, CSRF e limite de tentativas de login
# --------------------------------------------------------------------------
def csrf_token():
    if "csrf" not in session:
        session["csrf"] = secrets.token_urlsafe(32)
    return session["csrf"]


def csrf_ok():
    sent = request.headers.get("X-CSRF-Token") or request.form.get("csrf", "")
    return hmac.compare_digest(sent, session.get("csrf", ""))


def admin_required(fn):
    @wraps(fn)
    def wrapper(*args, **kwargs):
        if not session.get("admin"):
            return jsonify(error="Sessão expirada. Entre novamente em /admin."), 401
        if not csrf_ok():
            return jsonify(error="Token de segurança inválido. Recarregue a página."), 403
        return fn(*args, **kwargs)
    return wrapper


_attempts = {}            # ip -> (falhas, bloqueado_até)
_attempts_lock = threading.Lock()
MAX_FAILS, LOCK_SECONDS = 6, 300


def login_locked(ip):
    with _attempts_lock:
        fails, until = _attempts.get(ip, (0, 0))
        return until > time.time()


def login_fail(ip):
    with _attempts_lock:
        fails, until = _attempts.get(ip, (0, 0))
        if until and until <= time.time():
            fails = 0
        fails += 1
        _attempts[ip] = (fails, time.time() + LOCK_SECONDS if fails >= MAX_FAILS else 0)


def login_ok(ip):
    with _attempts_lock:
        _attempts.pop(ip, None)


@app.after_request
def security_headers(resp):
    resp.headers.setdefault("X-Content-Type-Options", "nosniff")
    resp.headers.setdefault("X-Frame-Options", "SAMEORIGIN")  # o painel embute a prévia
    resp.headers.setdefault("Referrer-Policy", "strict-origin-when-cross-origin")
    if request.path.startswith(("/admin", "/api")):
        resp.headers["Cache-Control"] = "no-store"
    return resp


# --------------------------------------------------------------------------
# Páginas
# --------------------------------------------------------------------------
@app.route("/")
def index():
    is_admin = bool(session.get("admin"))
    return render_template(
        "index.html",
        c=load_content(),
        slides=load_slides(),
        preview=is_admin and request.args.get("preview") == "1",
    )


@app.route("/admin", methods=["GET", "POST"])
def admin():
    ip = request.remote_addr or "?"
    if session.get("admin"):
        return render_template(
            "admin.html", c=load_content(), slides=load_slides(), csrf=csrf_token(),
            max_slides=MAX_SLIDES,
        )

    error = None
    if request.method == "POST":
        if not ADMIN_PASSWORD:
            error = "ADMIN_PASSWORD não está configurada no servidor."
        elif login_locked(ip):
            error = "Muitas tentativas. Aguarde alguns minutos e tente de novo."
        elif hmac.compare_digest(request.form.get("password", "").encode(), ADMIN_PASSWORD.encode()):
            login_ok(ip)
            session.clear()
            session["admin"] = True
            session.permanent = True
            csrf_token()
            return redirect(url_for("admin"))
        else:
            login_fail(ip)
            error = "Senha incorreta."
    return render_template("login.html", error=error), (401 if error else 200)


@app.route("/logout", methods=["POST"])
def logout():
    if session.get("admin") and not csrf_ok():
        return redirect(url_for("admin"))
    session.clear()
    return redirect(url_for("admin"))


@app.route("/uploads/<path:filename>")
def uploads(filename):
    return send_from_directory(UPLOAD_DIR, filename, max_age=60 * 60 * 24 * 30)


@app.route("/healthz")
def healthz():
    return "ok"


# --------------------------------------------------------------------------
# API do painel
# --------------------------------------------------------------------------
@app.route("/api/save", methods=["POST"])
@admin_required
def api_save():
    payload = request.get_json(silent=True) or {}
    content = payload.get("content", {})
    slides = payload.get("slides")

    if not isinstance(content, dict):
        return jsonify(error="Formato de conteúdo inválido."), 400

    updates = []
    for key, value in content.items():
        if key not in DEFAULT_CONTENT:
            continue
        if not isinstance(value, str):
            return jsonify(error=f"Valor inválido em {key}."), 400
        value = value.strip()
        if key in TEXT_LIMITS:
            value = value[:TEXT_LIMITS[key]]
        elif key in COLOR_KEYS:
            if not HEX_RE.match(value):
                return jsonify(error=f"Cor inválida ({key}). Use o formato #RRGGBB."), 400
            value = value.upper()
        elif key in IMAGE_KEYS:
            if value and not is_safe_image(value):
                return jsonify(error="Imagem inválida. Envie o arquivo pelo painel."), 400
        elif key in LINK_KEYS:
            if value and (not SAFE_LINK_RE.match(value) or len(value) > 800):
                return jsonify(error="Link inválido. Use um endereço que comece com https://"), 400
        elif key in BOOL_KEYS:
            value = "1" if value == "1" else "0"
        elif key in INT_RANGES:
            lo, hi = INT_RANGES[key]
            try:
                value = str(min(hi, max(lo, int(float(value)))))
            except ValueError:
                return jsonify(error=f"Número inválido ({key})."), 400
        elif key in CODE_KEYS:
            value = value[:8000]
        updates.append((key, value))

    clean_slides = None
    if slides is not None:
        if not isinstance(slides, list) or len(slides) > MAX_SLIDES:
            return jsonify(error=f"Lista de fotos inválida (máximo {MAX_SLIDES})."), 400
        clean_slides = []
        for pos, img in enumerate(slides):
            img = img.get("image", "") if isinstance(img, dict) else str(img)
            if not is_safe_image(img):
                return jsonify(error=f"Foto {pos + 1} do carrossel inválida."), 400
            clean_slides.append((img, pos))

    db = get_db()
    with db:  # transação: salva tudo ou nada
        db.executemany(
            """INSERT INTO content (key, value, updated_at) VALUES (?, ?, datetime('now'))
               ON CONFLICT(key) DO UPDATE SET value = excluded.value, updated_at = excluded.updated_at""",
            updates,
        )
        if clean_slides is not None:
            db.execute("DELETE FROM slides")
            db.executemany("INSERT INTO slides (image, position) VALUES (?, ?)", clean_slides)

    return jsonify(ok=True, content=load_content(), slides=load_slides())


@app.route("/api/upload", methods=["POST"])
@admin_required
def api_upload():
    file = request.files.get("file")
    if not file or not file.filename:
        return jsonify(error="Nenhum arquivo enviado."), 400
    ext = file.filename.rsplit(".", 1)[-1].lower() if "." in file.filename else ""
    if ext not in ALLOWED_EXT:
        return jsonify(error="Formato não aceito. Envie PNG, JPG, WEBP ou GIF."), 400

    head = file.stream.read(16)
    file.stream.seek(0)
    ok = (
        head.startswith((b"\x89PNG", b"\xff\xd8\xff", b"GIF8"))
        or (head.startswith(b"RIFF") and head[8:12] == b"WEBP")
    )
    if not ok:
        return jsonify(error="O arquivo não parece ser uma imagem válida."), 400

    name = f"{uuid.uuid4().hex}.{'jpg' if ext == 'jpeg' else ext}"
    file.save(os.path.join(UPLOAD_DIR, name))
    return jsonify(ok=True, url=f"/uploads/{name}")


@app.errorhandler(413)
def too_large(_e):
    return jsonify(error="Imagem muito grande. O limite é 8 MB."), 413


init_db()

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", "5000")), debug=True)
