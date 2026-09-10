import os
from datetime import datetime, timezone, timedelta
from functools import wraps

import requests
from dotenv import load_dotenv

from flask import (
    Flask,
    render_template,
    request,
    redirect,
    url_for,
    flash,
    jsonify,
    abort,
)

from flask_sqlalchemy import SQLAlchemy
from flask_login import (
    LoginManager,
    UserMixin,
    login_user,
    logout_user,
    current_user,
    login_required,
)

from werkzeug.security import generate_password_hash, check_password_hash


# ============================================================
# CONFIG
# ============================================================

load_dotenv()

BASE_DIR = os.path.abspath(os.path.dirname(__file__))

app = Flask(__name__)

app.config["SECRET_KEY"] = os.getenv(
    "SECRET_KEY",
    "CHANGE_THIS_SECRET_KEY_2026"
)

# Render için veritabanı URI ayarı.
# ÖNEMLİ: Render'da disk kalıcı DEĞİLDİR (her deploy/restart'ta sıfırlanır),
# bu yüzden SQLite fallback SADECE lokal geliştirme içindir.
# Render'da mutlaka DATABASE_URL env var'ı bir Render PostgreSQL veritabanına işaret etmelidir.
database_url = os.getenv("DATABASE_URL", "sqlite:///" + os.path.join(BASE_DIR, "tahmin_ligi.db"))
if database_url.startswith("postgres://"):
    database_url = database_url.replace("postgres://", "postgresql://", 1)

app.config["SQLALCHEMY_DATABASE_URI"] = database_url
app.config["SQLALCHEMY_TRACK_MODIFICATIONS"] = False
app.config["SQLALCHEMY_ENGINE_OPTIONS"] = {
    "pool_pre_ping": True,  # Render Postgres boşta kalan bağlantıyı kapatabilir; bu ayar hatayı önler
    "pool_recycle": 280,
}

db = SQLAlchemy(app)

login_manager = LoginManager(app)
login_manager.login_view = "giris"
login_manager.login_message = "Bu sayfayı görmek için giriş yapmalısınız."
login_manager.login_message_category = "warning"


# ============================================================
# FOOTBALL DATA API
# ============================================================

FOOTBALL_DATA_TOKEN = os.getenv(
    "FOOTBALL_DATA_TOKEN",
    ""
).strip()

FOOTBALL_DATA_BASE_URL = "https://api.football-data.org/v4"

CHAMPIONS_LEAGUE_CODE = "CL"
CHAMPIONS_LEAGUE_ID = 2001

API_TIMEOUT = 30


# ============================================================
# MODELS
# ============================================================

class Kullanici(UserMixin, db.Model):
    __tablename__ = "kullanicilar"

    id = db.Column(db.Integer, primary_key=True)

    kullanici_adi = db.Column(
        db.String(80),
        unique=True,
        nullable=False
    )

    sifre_hash = db.Column(
        db.String(255),
        nullable=False
    )

    admin = db.Column(
        db.Boolean,
        default=False
    )

    olusturulma = db.Column(
        db.DateTime,
        default=lambda: datetime.utcnow()
    )

    tahminler = db.relationship(
        "Tahmin",
        backref="kullanici",
        lazy=True,
        cascade="all, delete-orphan"
    )

    grup_uyelikleri = db.relationship(
        "GrupUyeligi",
        backref="kullanici",
        lazy=True,
        cascade="all, delete-orphan"
    )

    def set_password(self, password):
        self.sifre_hash = generate_password_hash(password)

    def check_password(self, password):
        return check_password_hash(
            self.sifre_hash,
            password
        )


class Grup(db.Model):
    __tablename__ = "gruplar"

    id = db.Column(
        db.Integer,
        primary_key=True
    )

    ad = db.Column(
        db.String(120),
        nullable=False
    )

    davet_kodu = db.Column(
        db.String(30),
        unique=True,
        nullable=False
    )

    sezon = db.Column(
        db.Integer,
        nullable=True
    )

    sosyal_kural = db.Column(
        db.Boolean,
        default=True
    )
    
    aciklama = db.Column(
        db.Text,
        nullable=True
    )

    kurucu_id = db.Column(
        db.Integer,
        db.ForeignKey("kullanicilar.id"),
        nullable=False
    )

    olusturulma = db.Column(
        db.DateTime,
        default=lambda: datetime.utcnow()
    )

    uyeler = db.relationship(
        "GrupUyeligi",
        backref="grup",
        lazy=True,
        cascade="all, delete-orphan"
    )

    tahminler = db.relationship(
        "Tahmin",
        backref="grup",
        lazy=True,
        cascade="all, delete-orphan"
    )


class GrupUyeligi(db.Model):
    __tablename__ = "grup_uyelikleri"

    id = db.Column(
        db.Integer,
        primary_key=True
    )

    grup_id = db.Column(
        db.Integer,
        db.ForeignKey("gruplar.id"),
        nullable=False
    )

    kullanici_id = db.Column(
        db.Integer,
        db.ForeignKey("kullanicilar.id"),
        nullable=False
    )

    katilma_tarihi = db.Column(
        db.DateTime,
        default=lambda: datetime.utcnow()
    )

    __table_args__ = (
        db.UniqueConstraint(
            "grup_id",
            "kullanici_id",
            name="unique_grup_kullanici"
        ),
    )


class Mac(db.Model):
    __tablename__ = "maclar"

    id = db.Column(
        db.Integer,
        primary_key=True
    )

    external_id = db.Column(
        db.Integer,
        unique=True,
        nullable=False
    )

    ev_sahibi = db.Column(
        db.String(150),
        nullable=False
    )

    deplasman = db.Column(
        db.String(150),
        nullable=False
    )

    ev_logo = db.Column(
        db.String(500)
    )

    deplasman_logo = db.Column(
        db.String(500)
    )

    lig = db.Column(
        db.String(100)
    )

    lig_id = db.Column(
        db.Integer
    )

    sezon = db.Column(
        db.Integer
    )

    hafta = db.Column(
        db.String(50)
    )

    baslangic = db.Column(
        db.DateTime
    )

    durum = db.Column(
        db.String(30)
    )

    api_status = db.Column(
        db.String(30)
    )

    ev_skor = db.Column(
        db.Integer,
        nullable=True
    )

    deplasman_skor = db.Column(
        db.Integer,
        nullable=True
    )

    son_guncelleme = db.Column(
        db.DateTime
    )

    tahminler = db.relationship(
        "Tahmin",
        backref="mac",
        lazy=True,
        cascade="all, delete-orphan"
    )

    def basladi_mi(self):
        if not self.baslangic:
            return False

        return self.baslangic <= utc_now_naive()

    def bitti_mi(self):
        return self.durum == "bitti"

    def oynanabilir_mi(self):
        if not self.baslangic:
            return False

        if self.durum in [
            "bitti",
            "iptal",
            "ertelendi"
        ]:
            return False

        return self.baslangic > utc_now_naive()


class Tahmin(db.Model):
    __tablename__ = "tahminler"

    id = db.Column(
        db.Integer,
        primary_key=True
    )

    grup_id = db.Column(
        db.Integer,
        db.ForeignKey("gruplar.id"),
        nullable=False
    )

    mac_id = db.Column(
        db.Integer,
        db.ForeignKey("maclar.id"),
        nullable=False
    )

    kullanici_id = db.Column(
        db.Integer,
        db.ForeignKey("kullanicilar.id"),
        nullable=False
    )

    ev_skor = db.Column(
        db.Integer,
        nullable=False
    )

    deplasman_skor = db.Column(
        db.Integer,
        nullable=False
    )

    puan = db.Column(
        db.Integer,
        default=0
    )

    olusturulma = db.Column(
        db.DateTime,
        default=lambda: datetime.utcnow()
    )

    guncellenme = db.Column(
        db.DateTime,
        default=lambda: datetime.utcnow(),
        onupdate=lambda: datetime.utcnow()
    )

    __table_args__ = (
        db.UniqueConstraint(
            "grup_id",
            "mac_id",
            "kullanici_id",
            name="unique_grup_mac_kullanici"
        ),
    )


# ============================================================
# LOGIN
# ============================================================

@login_manager.user_loader
def load_user(user_id):
    return db.session.get(
        Kullanici,
        int(user_id)
    )


# ============================================================
# HELPERS
# ============================================================

def utc_now_naive():
    return datetime.now(
        timezone.utc
    ).replace(
        tzinfo=None
    )


def parse_api_date(value):
    if not value:
        return None
    try:
        value = str(value)
        if value.endswith("Z"):
            value = value[:-1] + "+00:00"
        dt = datetime.fromisoformat(value)
        if dt.tzinfo:
            dt = dt.astimezone(timezone.utc).replace(tzinfo=None)
        return dt
    except Exception as e:
        print("Tarih parse hatası:", value, e)
        return None


def generate_invite_code(length=8):
    import secrets
    import string
    chars = string.ascii_uppercase + string.digits
    while True:
        code = "".join(secrets.choice(chars) for _ in range(length))
        if not Grup.query.filter_by(davet_kodu=code).first():
            return code


def admin_required(f):
    @wraps(f)
    def decorated(*args, **kwargs):
        if not current_user.is_authenticated:
            return redirect(url_for("giris"))
        if not current_user.admin:
            abort(403)
        return f(*args, **kwargs)
    return decorated


# ============================================================
# FOOTBALL API & SYNC
# ============================================================

def football_data_get(endpoint, params=None):
    if not FOOTBALL_DATA_TOKEN:
        raise RuntimeError("FOOTBALL_DATA_TOKEN bulunamadı.")
    url = FOOTBALL_DATA_BASE_URL.rstrip("/") + "/" + endpoint.lstrip("/")
    headers = {"X-Auth-Token": FOOTBALL_DATA_TOKEN, "Accept": "application/json"}
    response = requests.get(url, headers=headers, params=params or {}, timeout=API_TIMEOUT)
    if response.status_code != 200:
        raise RuntimeError(f"Football-Data API Hatası {response.status_code}: {response.text[:500]}")
    return response.json()


def map_match_status(api_status):
    mapping = {
        "FINISHED": "bitti",
        "CANCELLED": "iptal",
        "POSTPONED": "ertelendi",
        "SUSPENDED": "ertelendi",
        "IN_PLAY": "oynaniyor",
        "PAUSED": "oynaniyor",
        "TIMED": "planlandi",
        "SCHEDULED": "planlandi",
    }
    return mapping.get(api_status, "planlandi")


def football_match_to_db(match, competition_id=None, active_season=None):
    external_id = match.get("id")
    if not external_id:
        return None

    home_team = match.get("homeTeam") or {}
    away_team = match.get("awayTeam") or {}
    competition = match.get("competition") or {}
    season_data = match.get("season") or {}
    score = match.get("score") or {}
    full_time = score.get("fullTime") or {}

    season = active_season
    if season_data.get("startDate"):
        try:
            season = int(str(season_data["startDate"])[:4])
        except Exception:
            pass

    lig_id = competition_id
    if competition.get("id"):
        lig_id = competition.get("id")

    mac = Mac.query.filter_by(external_id=int(external_id)).first()
    if not mac:
        mac = Mac(external_id=int(external_id))
        db.session.add(mac)

    mac.ev_sahibi = home_team.get("name") or "Bilinmeyen Takım"
    mac.deplasman = away_team.get("name") or "Bilinmeyen Takım"
    mac.ev_logo = home_team.get("crest")
    mac.deplasman_logo = away_team.get("crest")
    mac.lig = competition.get("name") or "UEFA Champions League"
    mac.lig_id = lig_id
    mac.sezon = season
    mac.hafta = str(match.get("matchday")) if match.get("matchday") else None
    mac.baslangic = parse_api_date(match.get("utcDate"))
    mac.api_status = match.get("status")
    mac.durum = map_match_status(match.get("status"))

    home_score = full_time.get("home")
    away_score = full_time.get("away")
    if home_score is not None:
        mac.ev_skor = home_score
    if away_score is not None:
        mac.deplasman_skor = away_score

    mac.son_guncelleme = utc_now_naive()
    return mac


def sync_champions_league(requested_season=None):
    if not FOOTBALL_DATA_TOKEN:
        raise RuntimeError("FOOTBALL_DATA_TOKEN bulunamadı.")

    info = football_data_get(f"competitions/{CHAMPIONS_LEAGUE_CODE}")
    competition_id = info.get("id") or CHAMPIONS_LEAGUE_ID
    current_season = info.get("currentSeason") or {}
    api_season = None

    if current_season.get("startDate"):
        try:
            api_season = int(str(current_season["startDate"])[:4])
        except Exception:
            pass

    # ÖNEMLİ: dateFrom=today ile çekmek geçmişte kalan (oynanmış) maçları
    # bir daha hiç API'den döndürmediği için, o maçların skoru/puanı asla
    # güncellenmiyordu. Bunun yerine tüm sezonu "season" parametresiyle
    # çekiyoruz; böylece geçmiş, oynanan ve gelecek tüm maçlar her
    # senkronizasyonda güncellenir.
    season_to_use = requested_season or api_season
    response = football_data_get(
        f"competitions/{CHAMPIONS_LEAGUE_CODE}/matches",
        params={"season": season_to_use} if season_to_use else None,
    )
    matches = response.get("matches", [])

    inserted = 0
    updated = 0
    skipped = 0

    for match in matches:
        competition = match.get("competition") or {}
        if competition.get("code") != CHAMPIONS_LEAGUE_CODE:
            skipped += 1
            continue

        external_id = match.get("id")
        if not external_id:
            skipped += 1
            continue

        existing = Mac.query.filter_by(external_id=int(external_id)).first()
        season_data = match.get("season") or {}
        season = None
        if season_data.get("startDate"):
            try:
                season = int(str(season_data["startDate"])[:4])
            except Exception:
                pass

        result = football_match_to_db(match, competition_id=competition_id, active_season=season)
        if not result:
            skipped += 1
            continue

        if existing:
            updated += 1
        else:
            inserted += 1

    db.session.commit()
    recalculate_all_points()

    return {
        "success": True,
        "competition_id": competition_id,
        "api_matches": len(matches),
        "inserted": inserted,
        "updated": updated,
        "skipped": skipped
    }


def calculate_points(prediction_home, prediction_away, actual_home, actual_away):
    if actual_home is None or actual_away is None:
        return 0
    if prediction_home == actual_home and prediction_away == actual_away:
        return 5

    prediction_result = 1 if prediction_home > prediction_away else (-1 if prediction_home < prediction_away else 0)
    actual_result = 1 if actual_home > actual_away else (-1 if actual_home < actual_away else 0)

    if prediction_result == actual_result:
        return 3
    return 0


def recalculate_all_points():
    predictions = Tahmin.query.all()
    changed = False
    for tahmin in predictions:
        mac = tahmin.mac
        if not mac or not mac.bitti_mi() or mac.ev_skor is None or mac.deplasman_skor is None:
            continue
        new_points = calculate_points(tahmin.ev_skor, tahmin.deplasman_skor, mac.ev_skor, mac.deplasman_skor)
        if tahmin.puan != new_points:
            tahmin.puan = new_points
            changed = True
    if changed:
        db.session.commit()


# ============================================================
# DATABASE INITIALIZATION (Auto-run safely for Vercel)
# ============================================================

def initialize_database():
    with app.app_context():
        db.create_all()
        admin_username = os.getenv("ADMIN_USERNAME", "admin")
        admin_password = os.getenv("ADMIN_PASSWORD", "Admin123!")

        admin_user = Kullanici.query.filter_by(kullanici_adi=admin_username).first()
        if not admin_user:
            admin_user = Kullanici(kullanici_adi=admin_username, admin=True)
            admin_user.set_password(admin_password)
            db.session.add(admin_user)
            db.session.commit()
        elif not admin_user.admin:
            admin_user.admin = True
            db.session.commit()

# Her soğuk başlangıçta (cold start) veritabanı tablolarının var olduğundan emin olalım
initialize_database()


# ============================================================
# ROUTES (Rotalar)
# ============================================================

@app.route("/")
def index():
    if current_user.is_authenticated:
        return redirect(url_for("dashboard"))
    return redirect(url_for("giris"))


@app.route("/kayit", methods=["GET", "POST"])
def kayit():
    if current_user.is_authenticated:
        return redirect(url_for("dashboard"))
    next_url = request.args.get("next") or request.form.get("next") or ""
    if request.method == "POST":
        kullanici_adi = request.form.get("kullanici_adi", "").strip()
        sifre = request.form.get("sifre", "")
        sifre_tekrar = request.form.get("sifre_tekrar", "")

        if not kullanici_adi or len(sifre) < 6 or sifre != sifre_tekrar:
            flash("Form bilgilerini kontrol edin (Şifre en az 6 karakter olmalı ve uyuşmalı).", "danger")
            return redirect(url_for("kayit", next=next_url) if next_url else url_for("kayit"))

        if Kullanici.query.filter_by(kullanici_adi=kullanici_adi).first():
            flash("Bu kullanıcı adı zaten kullanılıyor.", "danger")
            return redirect(url_for("kayit", next=next_url) if next_url else url_for("kayit"))

        user = Kullanici(kullanici_adi=kullanici_adi)
        user.set_password(sifre)
        db.session.add(user)
        db.session.commit()
        flash("Kayıt başarılı. Şimdi giriş yapabilirsiniz.", "success")
        return redirect(url_for("giris", next=next_url) if next_url else url_for("giris"))
    return render_template("kayit.html", next_url=next_url)


@app.route("/giris", methods=["GET", "POST"])
def giris():
    if current_user.is_authenticated:
        return redirect(url_for("dashboard"))
    if request.method == "POST":
        kullanici_adi = request.form.get("kullanici_adi", "").strip()
        sifre = request.form.get("sifre", "")
        user = Kullanici.query.filter_by(kullanici_adi=kullanici_adi).first()
        if user and user.check_password(sifre):
            login_user(user)
            return redirect(request.args.get("next") or url_for("dashboard"))
        flash("Kullanıcı adı veya şifre hatalı.", "danger")
    return render_template("giris.html")


@app.route("/cikis")
@login_required
def cikis():
    logout_user()
    flash("Çıkış yapıldı.", "success")
    return redirect(url_for("giris"))


@app.route("/dashboard")
@login_required
def dashboard():
    now = utc_now_naive()
    yaklasan_maclar = Mac.query.filter(
        Mac.baslangic.isnot(None), Mac.baslangic > now,
        Mac.lig_id == CHAMPIONS_LEAGUE_ID,
        ~Mac.durum.in_(["bitti", "iptal", "ertelendi"])
    ).order_by(Mac.baslangic.asc()).limit(10).all()

    biten_maclar = Mac.query.filter(
        Mac.lig_id == CHAMPIONS_LEAGUE_ID, Mac.durum == "bitti"
    ).order_by(Mac.baslangic.desc()).limit(5).all()

    tahminler = {t.mac_id: t for t in Tahmin.query.filter_by(kullanici_id=current_user.id).all()}
    gruplar = [u.grup for u in GrupUyeligi.query.filter_by(kullanici_id=current_user.id).all()]
    toplam_puan = db.session.query(db.func.coalesce(db.func.sum(Tahmin.puan), 0)).filter(Tahmin.kullanici_id == current_user.id).scalar() or 0
    toplam_tahmin = Tahmin.query.filter_by(kullanici_id=current_user.id).count()

    return render_template(
        "dashboard.html",
        yaklasan_maclar=yaklasan_maclar,
        biten_maclar=biten_maclar,
        tahminler=tahminler,
        gruplar=gruplar,
        toplam_puan=toplam_puan,
        toplam_tahmin=toplam_tahmin,
        tahmin_edilen_maclar=toplam_tahmin
    )


@app.route("/gruplar")
@login_required
def gruplar():
    uyelikler = GrupUyeligi.query.filter_by(kullanici_id=current_user.id).all()
    return render_template("gruplar.html", gruplar=[u.grup for u in uyelikler])


@app.route("/grup-olustur", methods=["POST"])
@login_required
def grup_olustur():
    ad = request.form.get("ad", "").strip()
    aciklama = request.form.get("aciklama", "").strip()
    if not ad:
        flash("Grup adı girin.", "danger")
        return redirect(url_for("gruplar"))

    grup = Grup(ad=ad, aciklama=aciklama, davet_kodu=generate_invite_code(), sezon=2026, kurucu_id=current_user.id)
    db.session.add(grup)
    db.session.flush()
    db.session.add(GrupUyeligi(grup_id=grup.id, kullanici_id=current_user.id))
    db.session.commit()
    flash("Grup oluşturuldu.", "success")
    return redirect(url_for("grup", grup_id=grup.id))


@app.route("/grup-katil", methods=["POST"])
@login_required
def grup_katil():
    davet_kodu = request.form.get("davet_kodu", "").strip().upper()
    grup = Grup.query.filter_by(davet_kodu=davet_kodu).first()
    if not grup:
        flash("Geçersiz davet kodu.", "danger")
        return redirect(url_for("gruplar"))

    if GrupUyeligi.query.filter_by(grup_id=grup.id, kullanici_id=current_user.id).first():
        flash("Zaten bu grubun üyesisiniz.", "warning")
    else:
        db.session.add(GrupUyeligi(grup_id=grup.id, kullanici_id=current_user.id))
        db.session.commit()
        flash("Gruba katıldınız.", "success")
    return redirect(url_for("grup", grup_id=grup.id))


@app.route("/katil/<davet_kodu>")
def katil_link(davet_kodu):
    """
    Tek tıkla paylaşılabilir davet linki (örn. WhatsApp'a atılan link).
    Giriş yapılmamışsa önce kayıt/giriş ekranına yönlendirir, sonrasında
    otomatik olarak aynı linke geri dönüp gruba katılmayı tamamlar.
    """
    davet_kodu = davet_kodu.strip().upper()
    grup = Grup.query.filter_by(davet_kodu=davet_kodu).first()
    if not grup:
        flash("Geçersiz veya süresi dolmuş davet linki.", "danger")
        return redirect(url_for("giris") if not current_user.is_authenticated else url_for("gruplar"))

    if not current_user.is_authenticated:
        hedef = url_for("katil_link", davet_kodu=davet_kodu)
        flash(f"'{grup.ad}' grubuna katılmak için önce giriş yap ya da kayıt ol.", "success")
        return redirect(url_for("giris", next=hedef))

    if not GrupUyeligi.query.filter_by(grup_id=grup.id, kullanici_id=current_user.id).first():
        db.session.add(GrupUyeligi(grup_id=grup.id, kullanici_id=current_user.id))
        db.session.commit()
        flash(f"'{grup.ad}' grubuna katıldınız. 🎉", "success")

    return redirect(url_for("grup", grup_id=grup.id))


@app.route("/grup/<int:grup_id>")
@login_required
def grup(grup_id):
    grup_obj = db.session.get(Grup, grup_id)
    if not grup_obj or not GrupUyeligi.query.filter_by(grup_id=grup_id, kullanici_id=current_user.id).first():
        abort(403)

    now = utc_now_naive()
    en_yakin_mac = Mac.query.filter(Mac.lig_id == CHAMPIONS_LEAGUE_ID, Mac.baslangic.isnot(None), Mac.baslangic >= now).order_by(Mac.baslangic.asc()).first()
    hedef_hafta = en_yakin_mac.hafta if en_yakin_mac and en_yakin_mac.hafta else None

    if hedef_hafta:
        maclar = Mac.query.filter(Mac.lig_id == CHAMPIONS_LEAGUE_ID, Mac.hafta == hedef_hafta).order_by(Mac.baslangic.asc()).all()
    else:
        maclar = Mac.query.filter(Mac.lig_id == CHAMPIONS_LEAGUE_ID).order_by(Mac.baslangic.desc()).limit(10).all()

    tahmin_dict = {t.mac_id: t for t in Tahmin.query.filter_by(grup_id=grup_id, kullanici_id=current_user.id).all()}
    members = GrupUyeligi.query.filter_by(grup_id=grup_id).all()
    
    grup_tahmin_matrisi = {}
    for t in Tahmin.query.filter_by(grup_id=grup_id).all():
        grup_tahmin_matrisi.setdefault(t.mac_id, {})[t.kullanici_id] = t

    leaderboard = sorted([
        {"user": m.kullanici, "points": int(db.session.query(db.func.coalesce(db.func.sum(Tahmin.puan), 0)).filter(Tahmin.grup_id == grup_id, Tahmin.kullanici_id == m.kullanici_id).scalar() or 0)}
        for m in members
    ], key=lambda x: x["points"], reverse=True)

    return render_template(
        "grup.html",
        grup=grup_obj,
        maclar=maclar,
        aktif_hafta=hedef_hafta,
        tahminler=tahmin_dict,
        members=members,
        grup_tahmin_matrisi=grup_tahmin_matrisi,
        leaderboard=leaderboard
    )


@app.route("/tahmin/<int:grup_id>/<int:mac_id>", methods=["GET", "POST"])
@login_required
def tahmin(grup_id, mac_id):
    membership = GrupUyeligi.query.filter_by(grup_id=grup_id, kullanici_id=current_user.id).first()
    mac = db.session.get(Mac, mac_id)
    if not membership or not mac:
        abort(403)

    if not mac.oynanabilir_mi():
        flash("Bu maç için artık tahmin yapılamaz.", "warning")
        return redirect(url_for("grup", grup_id=grup_id))

    existing = Tahmin.query.filter_by(grup_id=grup_id, mac_id=mac_id, kullanici_id=current_user.id).first()

    if request.method == "POST":
        try:
            ev_skor = int(request.form.get("ev_skor"))
            deplasman_skor = int(request.form.get("deplasman_skor"))
        except Exception:
            flash("Skorları doğru girin.", "danger")
            return redirect(url_for("tahmin", grup_id=grup_id, mac_id=mac_id))

        if ev_skor < 0 or deplasman_skor < 0:
            flash("Skor negatif olamaz.", "danger")
            return redirect(url_for("tahmin", grup_id=grup_id, mac_id=mac_id))

        if existing:
            existing.ev_skor = ev_skor
            existing.deplasman_skor = deplasman_skor
            existing.guncellenme = datetime.utcnow()
        else:
            db.session.add(Tahmin(grup_id=grup_id, mac_id=mac_id, kullanici_id=current_user.id, ev_skor=ev_skor, deplasman_skor=deplasman_skor, puan=0))

        db.session.commit()
        flash("Tahmininiz kaydedildi.", "success")
        return redirect(url_for("grup", grup_id=grup_id))

    return render_template("tahmin.html", grup=membership.grup, mac=mac, tahmin=existing)


@app.route("/profil")
@login_required
def profil():
    total_points = db.session.query(db.func.coalesce(db.func.sum(Tahmin.puan), 0)).filter(Tahmin.kullanici_id == current_user.id).scalar() or 0
    prediction_count = Tahmin.query.filter_by(kullanici_id=current_user.id).count()
    return render_template("profil.html", toplam_puan=total_points, toplam_tahmin=prediction_count)


@app.route("/admin")
@admin_required
def admin():
    kullanici_sayisi = Kullanici.query.count()
    grup_sayisi = Grup.query.count()
    mac_sayisi = Mac.query.count()
    cl_mac_sayisi = Mac.query.filter(Mac.lig_id == CHAMPIONS_LEAGUE_ID).count()
    tahmin_sayisi = Tahmin.query.count()
    upcoming_matches = Mac.query.filter(
        Mac.baslangic.isnot(None), Mac.baslangic > utc_now_naive(),
        Mac.lig_id == CHAMPIONS_LEAGUE_ID,
        ~Mac.durum.in_(["bitti", "iptal", "ertelendi"])
    ).count()
    return render_template(
        "admin.html",
        kullanici_sayisi=kullanici_sayisi,
        grup_sayisi=grup_sayisi,
        mac_sayisi=mac_sayisi,
        cl_mac_sayisi=cl_mac_sayisi,
        tahmin_sayisi=tahmin_sayisi,
        # eski isimler de duruyor, başka bir yerde kullanan varsa bozulmasın
        total_users=kullanici_sayisi,
        total_groups=grup_sayisi,
        total_matches=mac_sayisi,
        total_predictions=tahmin_sayisi,
        upcoming_matches=upcoming_matches
    )


@app.route("/admin/durum")
@admin_required
def admin_durum():
    ornek_maclar = Mac.query.filter(Mac.lig_id == CHAMPIONS_LEAGUE_ID).order_by(Mac.baslangic.desc()).limit(5).all()
    if not ornek_maclar:
        flash("Veritabanında hiç Champions League maçı yok. 'Şimdi Sync Et' ile veri çekmeyi dene.", "warning")
    else:
        ornekler = "; ".join(f"{m.ev_sahibi}-{m.deplasman} ({m.durum}, hafta {m.hafta})" for m in ornek_maclar)
        flash(f"DB'de {Mac.query.filter(Mac.lig_id == CHAMPIONS_LEAGUE_ID).count()} CL maçı var. Son 5: {ornekler}", "success")
    return redirect(url_for("admin"))


@app.route("/admin/sync", methods=["GET", "POST"])
@admin_required
def admin_sync():
    try:
        result = sync_champions_league()
        flash(f"Senkronizasyon tamamlandı. API: {result['api_matches']} | Yeni: {result['inserted']} | Güncellenen: {result['updated']}", "success")
    except Exception as e:
        db.session.rollback()
        flash(f"Senkronizasyon hatası: {e}", "danger")
    return redirect(url_for("admin"))


@app.route("/admin/api-test")
@admin_required
def admin_api_test():
    if not FOOTBALL_DATA_TOKEN:
        flash("FOOTBALL_DATA_TOKEN tanımlı değil (env var eksik).", "danger")
        return redirect(url_for("admin"))
    try:
        info = football_data_get(f"competitions/{CHAMPIONS_LEAGUE_CODE}")
        isim = info.get("name", "?")
        sezon = (info.get("currentSeason") or {}).get("startDate", "?")
        flash(f"API bağlantısı başarılı. Yarışma: {isim} | Sezon başlangıcı: {sezon}", "success")
    except Exception as e:
        flash(f"API bağlantı hatası: {e}", "danger")
    return redirect(url_for("admin"))


@app.route("/cron/sync", methods=["GET", "POST"])
def cron_sync():
    """
    Render Cron Job / dış zamanlayıcı tarafından çağrılacak endpoint.
    Login gerektirmez, bunun yerine CRON_SECRET ile korunur.
    Kullanım: curl -H "X-Cron-Secret: <secret>" https://.../cron/sync
    veya:     curl https://.../cron/sync?secret=<secret>
    """
    beklenen_secret = os.getenv("CRON_SECRET", "").strip()
    if not beklenen_secret:
        return jsonify({"success": False, "error": "CRON_SECRET tanımlı değil (env var eksik)."}), 500

    gelen_secret = request.headers.get("X-Cron-Secret") or request.args.get("secret") or ""
    if gelen_secret != beklenen_secret:
        abort(403)

    try:
        result = sync_champions_league()
        return jsonify(result), 200
    except Exception as e:
        db.session.rollback()
        return jsonify({"success": False, "error": str(e)}), 500


@app.errorhandler(403)
def forbidden(error):
    return "<h1>403</h1><p>Bu sayfaya erişim yetkiniz yok.</p>", 403

@app.errorhandler(404)
def not_found(error):
    return "<h1>404</h1><p>Sayfa bulunamadı.</p>", 404

@app.errorhandler(500)
def internal_error(error):
    db.session.rollback()
    return "<h1>500</h1><p>Sunucu tarafında bir hata oluştu.</p>", 500


if __name__ == "__main__":
    app.run(host="127.0.0.1", port=5000, debug=False)