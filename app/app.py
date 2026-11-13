"""
Landing page editável — Hélder Sorteios
Flask + SQLite. Todo o conteúdo (textos, imagens, cores, links, carrossel)
fica no banco e é editado em /admin. Salvou, vale na hora para todo mundo.
"""
import hashlib
import hmac
import io
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
    Flask, g, jsonify, make_response, redirect, render_template, request,
    send_from_directory, session, url_for,
)
from flask_compress import Compress
from PIL import Image, ImageOps, UnidentifiedImageError
from werkzeug.middleware.proxy_fix import ProxyFix

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
DATA_DIR = os.environ.get("DATA_DIR", os.path.join(BASE_DIR, "data"))
DB_PATH = os.path.join(DATA_DIR, "lp.sqlite3")
UPLOAD_DIR = os.path.join(DATA_DIR, "uploads")
Image.MAX_IMAGE_PIXELS = 40_000_000   # barra "bombas" de descompressão
MAX_IMAGE_SIDE = 1920                  # uploads são reduzidos a isso
PAGE_TTL = 5                           # s: cache do HTML renderizado em cada worker
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
    SEND_FILE_MAX_AGE_DEFAULT=timedelta(days=365),   # /static e /uploads: URLs versionadas
    COMPRESS_ALGORITHM=["br", "gzip"],
    COMPRESS_MIN_SIZE=500,
    COMPRESS_LEVEL=6,
    COMPRESS_BR_LEVEL=4,
)
Compress(app)
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
    "favicon_image": "/static/img/logo.webp",
    "head_code": "",
    # Logo
    "show_logo": "0",
    "logo_image": "/static/img/logo.webp",
    "logo_alt": "HS Hélder Sorteios",
    # Topo
    "hero_title": "Golf GTI",
    "hero_title_accent": "STAGE 2",
    "hero_accent_image": "/static/img/stage2.webp",
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
    "/static/img/premio/golf-frente.webp",
    "/static/img/premio/golf-lateral.webp",
    "/static/img/premio/golf-painel.webp",
    "/static/img/premio/golf-bancos.webp",
    "/static/img/premio/golf-banco-traseiro.webp",
]

# Caminhos antigos (jpg/png) → versões otimizadas. Aplicado ao subir, em bancos já existentes.
LEGACY_PATHS = {
    f"/static/img/premio/golf-{n}.jpg": f"/static/img/premio/golf-{n}.webp"
    for n in ("frente", "lateral", "painel", "bancos", "banco-traseiro")
}
LEGACY_PATHS.update({"/static/img/stage2.webp": "/static/img/stage2.webp", "/static/img/logo.webp": "/static/img/logo.webp"})

# Caminhos antigos (jpg/png) -> versões otimizadas. Aplicado ao subir, em bancos já existentes.
LEGACY_PATHS = {
    f"/static/img/premio/golf-{n}.jpg": f"/static/img/premio/golf-{n}.webp"
    for n in ("frente", "lateral", "painel", "bancos", "banco-traseiro")
}
LEGACY_PATHS.update({"/static/img/stage2.png": "/static/img/stage2.webp", "/static/img/logo.png": "/static/img/logo.webp"})

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
        g.db.execute("PRAGMA synchronous=NORMAL")
        g.db.execute("PRAGMA synchronous=NORMAL")
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
        CREATE INDEX IF NOT EXISTS idx_slides_order ON slides (position, id);
        CREATE INDEX IF NOT EXISTS idx_slides_order ON slides (position, id);
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
    for old, new in LEGACY_PATHS.items():
        db.execute("UPDATE content SET value = ? WHERE value = ?", (new, old))
        db.execute("UPDATE slides SET image = ? WHERE image = ?", (new, old))
    db.execute("PRAGMA optimize")
    for old, new in LEGACY_PATHS.items():
        db.execute("UPDATE content SET value = ? WHERE value = ?", (new, old))
        db.execute("UPDATE slides SET image = ? WHERE image = ?", (new, old))
    db.execute("PRAGMA optimize")
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
        if len(_attempts) > 2000:  # evita crescer sem limite
            now = time.time()
            for k in [k for k, (_, until) in _attempts.items() if until <= now]:
                del _attempts[k]
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
    h = resp.headers
    h.setdefault("X-Content-Type-Options", "nosniff")
    h.setdefault("X-Frame-Options", "SAMEORIGIN")  # o painel embute a prévia
    h.setdefault("Referrer-Policy", "strict-origin-when-cross-origin")
    if request.is_secure:
        h.setdefault("Strict-Transport-Security", "max-age=31536000")
    if request.path.startswith(("/admin", "/api", "/logout")):
        h["Cache-Control"] = "no-store"
    elif request.path.startswith(("/static/", "/uploads/")) and resp.status_code in (200, 304):
        # Arquivos versionados (?v=) ou com nome único: o navegador guarda por 1 ano
        h["Cache-Control"] = "public, max-age=31536000, immutable"
    return resp


# URLs de estáticos com ?v=<data de modificação>: cache longo sem servir arquivo velho
_mtimes = {}


def versioned(path):
    """'/static/img/x.webp' -> '/static/img/x.webp?v=1731...'; outros caminhos passam direto."""
    if not isinstance(path, str) or not path.startswith("/static/"):
        return path
    if path not in _mtimes:
        try:
            _mtimes[path] = int(os.path.getmtime(os.path.join(BASE_DIR, path.lstrip("/"))))
        except OSError:
            return path
    return f"{path}?v={_mtimes[path]}"


app.jinja_env.filters["ver"] = versioned
app.jinja_env.globals["static_v"] = lambda name: versioned(url_for("static", filename=name))


# --------------------------------------------------------------------------
# Páginas
# --------------------------------------------------------------------------
_page = {"at": 0.0, "html": "", "etag": ""}
_page_lock = threading.Lock()


def public_page():
    """HTML público pronto + ETag. Fica em memória por poucos segundos em cada worker
    (e é descartado na hora quando o admin salva): a página não consulta o banco a cada visita."""
    now = time.monotonic()
    if _page["html"] and now - _page["at"] < PAGE_TTL:
        return _page["html"], _page["etag"]
    html = render_template("index.html", c=load_content(), slides=load_slides(), preview=False)
    etag = hashlib.sha1(html.encode()).hexdigest()[:20]
    with _page_lock:
        _page.update(at=now, html=html, etag=etag)
    return html, etag


@app.route("/")
def index():
    # Só abre a sessão se o visitante tem cookie (evita Vary: Cookie para o público)
    is_admin = "session" in request.cookies and bool(session.get("admin"))
    if is_admin:
        resp = make_response(render_template(
            "index.html", c=load_content(), slides=load_slides(),
            preview=request.args.get("preview") == "1"))
        resp.headers["Cache-Control"] = "private, no-store"
        return resp
    html, etag = public_page()
    resp = make_response(html)
    resp.set_etag(etag)
    resp.headers["Cache-Control"] = "public, max-age=30, stale-while-revalidate=120"
    return resp.make_conditional(request)


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

    _page["at"] = 0.0
    _page["html"] = ""
    return jsonify(ok=True, content=load_content(), slides=load_slides())


@app.route("/api/upload", methods=["POST"])
@admin_required
def api_upload():
    file = request.files.get("file")
    if not file or not file.filename:
        return jsonify(error="Nenhum arquivo enviado."), 400
    raw = file.read()
    try:
        img = Image.open(io.BytesIO(raw))
        fmt = img.format
        if fmt not in ("PNG", "JPEG", "WEBP", "GIF"):
            return jsonify(error="Formato não aceito. Envie PNG, JPG, WEBP ou GIF."), 400
        name = uuid.uuid4().hex
        if fmt == "GIF" and getattr(img, "is_animated", False):
            name += ".gif"                       # GIF animado: mantém o original
            data = raw
        else:
            # Corrige a rotação do celular, limita o tamanho e converte para WebP (bem menor)
            img = ImageOps.exif_transpose(img)
            img.thumbnail((MAX_IMAGE_SIDE, MAX_IMAGE_SIDE))
            img = img.convert("RGBA" if "A" in img.getbands() or img.mode == "P" else "RGB")
            buf = io.BytesIO()
            img.save(buf, "WEBP", quality=82, method=4)
            name += ".webp"
            data = buf.getvalue()
    except (UnidentifiedImageError, OSError, Image.DecompressionBombError, ValueError):
        return jsonify(error="O arquivo não parece ser uma imagem válida."), 400

    with open(os.path.join(UPLOAD_DIR, name), "wb") as f:
        f.write(data)
    return jsonify(ok=True, url=f"/uploads/{name}")


@app.errorhandler(413)
def too_large(_e):
    return jsonify(error="Imagem muito grande. O limite é 8 MB."), 413


init_db()

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", "5000")), debug=True)
