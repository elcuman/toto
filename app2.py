import os
import threading
import time
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

app.config["SQLALCHEMY_DATABASE_URI"] = (
    "sqlite:///" + os.path.join(BASE_DIR, "tahmin_ligi.db")
)

app.config["SQLALCHEMY_TRACK_MODIFICATIONS"] = False

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

SYNC_INTERVAL_MINUTES = int(
    os.getenv("SYNC_INTERVAL_MINUTES", "120")
)

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
            dt = dt.astimezone(
                timezone.utc
            ).replace(
                tzinfo=None
            )

        return dt

    except Exception as e:

        print(
            "Tarih parse hatası:",
            value,
            e
        )

        return None


def generate_invite_code(length=8):

    import secrets
    import string

    chars = (
        string.ascii_uppercase +
        string.digits
    )

    while True:

        code = "".join(
            secrets.choice(chars)
            for _ in range(length)
        )

        if not Grup.query.filter_by(
            davet_kodu=code
        ).first():

            return code


def admin_required(f):

    @wraps(f)
    def decorated(*args, **kwargs):

        if not current_user.is_authenticated:
            return redirect(
                url_for("giris")
            )

        if not current_user.admin:
            abort(403)

        return f(*args, **kwargs)

    return decorated


# ============================================================
# FOOTBALL API
# ============================================================

def football_data_get(endpoint, params=None):

    if not FOOTBALL_DATA_TOKEN:
        raise RuntimeError(
            "FOOTBALL_DATA_TOKEN bulunamadı. "
            ".env dosyanı kontrol et."
        )

    url = (
        FOOTBALL_DATA_BASE_URL.rstrip("/")
        + "/"
        + endpoint.lstrip("/")
    )

    headers = {
        "X-Auth-Token": FOOTBALL_DATA_TOKEN,
        "Accept": "application/json"
    }

    response = requests.get(
        url,
        headers=headers,
        params=params or {},
        timeout=API_TIMEOUT
    )

    if response.status_code != 200:

        raise RuntimeError(
            f"Football-Data API Hatası "
            f"{response.status_code}: "
            f"{response.text[:500]}"
        )

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

    return mapping.get(
        api_status,
        "planlandi"
    )


# ============================================================
# API MATCH -> DATABASE
# ============================================================

def football_match_to_db(
    match,
    competition_id=None,
    active_season=None
):

    external_id = match.get("id")

    if not external_id:
        return None

    home_team = match.get(
        "homeTeam"
    ) or {}

    away_team = match.get(
        "awayTeam"
    ) or {}

    competition = match.get(
        "competition"
    ) or {}

    season_data = match.get(
        "season"
    ) or {}

    score = match.get(
        "score"
    ) or {}

    full_time = score.get(
        "fullTime"
    ) or {}

    season = active_season

    if season_data.get(
        "startDate"
    ):

        try:

            season = int(
                str(
                    season_data["startDate"]
                )[:4]
            )

        except Exception:
            pass

    lig_id = competition_id

    if competition.get("id"):
        lig_id = competition.get("id")

    mac = Mac.query.filter_by(
        external_id=int(external_id)
    ).first()

    if not mac:

        mac = Mac(
            external_id=int(external_id)
        )

        db.session.add(mac)

    mac.ev_sahibi = (
        home_team.get("name")
        or "Bilinmeyen Takım"
    )

    mac.deplasman = (
        away_team.get("name")
        or "Bilinmeyen Takım"
    )

    mac.ev_logo = home_team.get(
        "crest"
    )

    mac.deplasman_logo = away_team.get(
        "crest"
    )

    mac.lig = (
        competition.get("name")
        or "UEFA Champions League"
    )

    mac.lig_id = lig_id

    mac.sezon = season

    mac.hafta = (
        str(match.get("matchday"))
        if match.get("matchday")
        else None
    )

    mac.baslangic = parse_api_date(
        match.get("utcDate")
    )

    mac.api_status = match.get(
        "status"
    )

    mac.durum = map_match_status(
        match.get("status")
    )

    home_score = full_time.get(
        "home"
    )

    away_score = full_time.get(
        "away"
    )

    if home_score is not None:
        mac.ev_skor = home_score

    if away_score is not None:
        mac.deplasman_skor = away_score

    mac.son_guncelleme = utc_now_naive()

    return mac


# ============================================================
# SYNC CHAMPIONS LEAGUE
# ============================================================

def sync_champions_league(
    requested_season=None
):

    if not FOOTBALL_DATA_TOKEN:

        raise RuntimeError(
            "FOOTBALL_DATA_TOKEN bulunamadı."
        )

    now = datetime.now(
        timezone.utc
    )

    today = now.strftime(
        "%Y-%m-%d"
    )

    future_date = (
        now + timedelta(days=365)
    ).strftime(
        "%Y-%m-%d"
    )

    info = football_data_get(
        f"competitions/{CHAMPIONS_LEAGUE_CODE}"
    )

    competition_id = (
        info.get("id")
        or CHAMPIONS_LEAGUE_ID
    )

    current_season = (
        info.get("currentSeason")
        or {}
    )

    api_season = None

    if current_season.get(
        "startDate"
    ):

        try:

            api_season = int(
                str(
                    current_season[
                        "startDate"
                    ]
                )[:4]
            )

        except Exception:
            pass

    response = football_data_get(
        f"competitions/{CHAMPIONS_LEAGUE_CODE}/matches",
        params={
            "dateFrom": today,
            "dateTo": future_date
        }
    )

    matches = response.get(
        "matches",
        []
    )

    if not matches:

        season_to_use = (
            requested_season
            or api_season
        )

        if season_to_use:

            response = football_data_get(
                f"competitions/{CHAMPIONS_LEAGUE_CODE}/matches",
                params={
                    "season": season_to_use
                }
            )

            matches = response.get(
                "matches",
                []
            )

    inserted = 0
    updated = 0
    skipped = 0

    for match in matches:

        competition = (
            match.get("competition")
            or {}
        )

        if competition.get(
            "code"
        ) != CHAMPIONS_LEAGUE_CODE:

            skipped += 1
            continue

        external_id = match.get(
            "id"
        )

        if not external_id:

            skipped += 1
            continue

        existing = Mac.query.filter_by(
            external_id=int(external_id)
        ).first()

        season_data = (
            match.get("season")
            or {}
        )

        season = None

        if season_data.get(
            "startDate"
        ):

            try:

                season = int(
                    str(
                        season_data[
                            "startDate"
                        ]
                    )[:4]
                )

            except Exception:
                pass

        result = football_match_to_db(
            match,
            competition_id=competition_id,
            active_season=season
        )

        if not result:

            skipped += 1
            continue

        if existing:
            updated += 1
        else:
            inserted += 1

    db.session.commit()

    latest_season = (
        db.session.query(
            db.func.max(
                Mac.sezon
            )
        )
        .filter(
            Mac.lig_id ==
            competition_id
        )
        .scalar()
    )

    if latest_season:

        Grup.query.update(
            {
                Grup.sezon:
                latest_season
            },
            synchronize_session=False
        )

        db.session.commit()

    recalculate_all_points()

    total_matches = Mac.query.count()

    upcoming_matches = (
        Mac.query
        .filter(
            Mac.baslangic.isnot(None),

            Mac.baslangic >
            utc_now_naive(),

            Mac.lig_id ==
            competition_id,

            ~Mac.durum.in_(
                [
                    "bitti",
                    "iptal",
                    "ertelendi"
                ]
            )
        )
        .count()
    )

    return {

        "success": True,

        "competition_id":
            competition_id,

        "api_matches":
            len(matches),

        "inserted":
            inserted,

        "updated":
            updated,

        "skipped":
            skipped,

        "db_total_matches":
            total_matches,

        "upcoming_matches":
            upcoming_matches,

        "season":
            latest_season
    }


# ============================================================
# SCORING
# ============================================================

def calculate_points(
    prediction_home,
    prediction_away,
    actual_home,
    actual_away
):

    if actual_home is None:
        return 0

    if actual_away is None:
        return 0

    if (
        prediction_home ==
        actual_home
        and
        prediction_away ==
        actual_away
    ):

        return 5

    prediction_result = (
        1
        if prediction_home > prediction_away
        else -1
        if prediction_home < prediction_away
        else 0
    )

    actual_result = (
        1
        if actual_home > actual_away
        else -1
        if actual_home < actual_away
        else 0
    )

    if prediction_result == actual_result:
        return 3

    return 0


def recalculate_all_points():

    predictions = Tahmin.query.all()

    changed = False

    for tahmin in predictions:

        mac = tahmin.mac

        if not mac:
            continue

        if not mac.bitti_mi():
            continue

        if (
            mac.ev_skor is None
            or
            mac.deplasman_skor is None
        ):
            continue

        new_points = calculate_points(
            tahmin.ev_skor,
            tahmin.deplasman_skor,
            mac.ev_skor,
            mac.deplasman_skor
        )

        if tahmin.puan != new_points:

            tahmin.puan = new_points
            changed = True

    if changed:
        db.session.commit()


# ============================================================
# HOME
# ============================================================

@app.route("/")
def index():

    if current_user.is_authenticated:
        return redirect(
            url_for("dashboard")
        )

    return redirect(
        url_for("giris")
    )


# ============================================================
# REGISTER
# ============================================================

@app.route(
    "/kayit",
    methods=["GET", "POST"]
)
def kayit():

    if current_user.is_authenticated:
        return redirect(
            url_for("dashboard")
        )

    if request.method == "POST":

        kullanici_adi = (
            request.form
            .get("kullanici_adi", "")
            .strip()
        )

        sifre = request.form.get(
            "sifre",
            ""
        )
        
        sifre_tekrar = request.form.get(
            "sifre_tekrar",
            ""
        )

        if not kullanici_adi:
            flash("Kullanıcı adı girin.", "danger")
            return redirect(url_for("kayit"))

        if len(sifre) < 6:
            flash("Şifre en az 6 karakter olmalı.", "danger")
            return redirect(url_for("kayit"))

        if sifre != sifre_tekrar:
            flash("Şifreler birbiriyle uyuşmuyor.", "danger")
            return redirect(url_for("kayit"))

        existing = Kullanici.query.filter_by(
            kullanici_adi=kullanici_adi
        ).first()

        if existing:
            flash("Bu kullanıcı adı zaten kullanılıyor.", "danger")
            return redirect(url_for("kayit"))

        user = Kullanici(
            kullanici_adi=kullanici_adi
        )

        user.set_password(sifre)

        db.session.add(user)
        db.session.commit()

        flash("Kayıt başarılı. Şimdi giriş yapabilirsiniz.", "success")

        return redirect(url_for("giris"))

    return render_template("kayit.html")


# ============================================================
# LOGIN
# ============================================================

@app.route(
    "/giris",
    methods=["GET", "POST"]
)
def giris():

    if current_user.is_authenticated:
        return redirect(
            url_for("dashboard")
        )

    if request.method == "POST":

        kullanici_adi = (
            request.form
            .get("kullanici_adi", "")
            .strip()
        )

        sifre = request.form.get(
            "sifre",
            ""
        )

        user = Kullanici.query.filter_by(
            kullanici_adi=kullanici_adi
        ).first()

        if (
            user
            and
            user.check_password(sifre)
        ):

            login_user(user)

            next_page = request.args.get(
                "next"
            )

            if next_page:
                return redirect(
                    next_page
                )

            return redirect(
                url_for("dashboard")
            )

        flash(
            "Kullanıcı adı veya şifre hatalı.",
            "danger"
        )

    return render_template(
        "giris.html"
    )


# ============================================================
# LOGOUT
# ============================================================

@app.route("/cikis")
@login_required
def cikis():

    logout_user()

    flash(
        "Çıkış yapıldı.",
        "success"
    )

    return redirect(
        url_for("giris")
    )


# ============================================================
# DASHBOARD
# ============================================================

@app.route("/dashboard")
@login_required
def dashboard():

    now = utc_now_naive()

    yaklasan_maclar = (
        Mac.query
        .filter(
            Mac.baslangic.isnot(None),
            Mac.baslangic > now,
            Mac.lig_id == CHAMPIONS_LEAGUE_ID,
            ~Mac.durum.in_(["bitti", "iptal", "ertelendi"])
        )
        .order_by(
            Mac.baslangic.asc()
        )
        .limit(10)
        .all()
    )

    biten_maclar = (
        Mac.query
        .filter(
            Mac.lig_id == CHAMPIONS_LEAGUE_ID,
            Mac.durum == "bitti"
        )
        .order_by(
            Mac.baslangic.desc()
        )
        .limit(5)
        .all()
    )

    tahminler = Tahmin.query.filter_by(
        kullanici_id=current_user.id
    ).all()

    tahmin_dict = {
        t.mac_id: t
        for t in tahminler
    }

    uyelikler = (
        GrupUyeligi.query
        .filter_by(
            kullanici_id=current_user.id
        )
        .all()
    )

    gruplar = [
        u.grup
        for u in uyelikler
    ]

    toplam_puan = (
        db.session.query(
            db.func.coalesce(
                db.func.sum(
                    Tahmin.puan
                ),
                0
            )
        )
        .filter(
            Tahmin.kullanici_id ==
            current_user.id
        )
        .scalar()
        or 0
    )

    toplam_tahmin = (
        Tahmin.query
        .filter_by(
            kullanici_id=current_user.id
        )
        .count()
    )

    return render_template(
        "dashboard.html",

        yaklasan_maclar=
            yaklasan_maclar,

        biten_maclar=
            biten_maclar,

        tahminler=
            tahmin_dict,

        gruplar=
            gruplar,

        toplam_puan=
            toplam_puan,

        toplam_tahmin=
            toplam_tahmin,

        tahmin_edilen_maclar=
            toplam_tahmin
    )


# ============================================================
# GROUPS
# ============================================================

@app.route("/gruplar")
@login_required
def gruplar():

    uyelikler = (
        GrupUyeligi.query
        .filter_by(
            kullanici_id=current_user.id
        )
        .all()
    )

    gruplar = [
        u.grup
        for u in uyelikler
    ]

    return render_template(
        "gruplar.html",
        gruplar=gruplar
    )


# ============================================================
# CREATE GROUP
# ============================================================

@app.route(
    "/grup-olustur",
    methods=["POST"]
)
@login_required
def grup_olustur():

    ad = (
        request.form
        .get("ad", "")
        .strip()
    )
    
    aciklama = (
        request.form
        .get("aciklama", "")
        .strip()
    )

    if not ad:

        flash(
            "Grup adı girin.",
            "danger"
        )

        return redirect(
            url_for("gruplar")
        )

    grup = Grup(
        ad=ad,
        aciklama=aciklama,
        davet_kodu=generate_invite_code(),
        sezon=2026,
        kurucu_id=current_user.id
    )

    db.session.add(grup)
    db.session.flush()

    membership = GrupUyeligi(
        grup_id=grup.id,
        kullanici_id=current_user.id
    )

    db.session.add(
        membership
    )

    db.session.commit()

    flash(
        "Grup oluşturuldu.",
        "success"
    )

    return redirect(
        url_for(
            "grup",
            grup_id=grup.id
        )
    )


# ============================================================
# JOIN GROUP
# ============================================================

@app.route(
    "/grup-katil",
    methods=["POST"]
)
@login_required
def grup_katil():

    davet_kodu = (
        request.form
        .get("davet_kodu", "")
        .strip()
        .upper()
    )

    grup = Grup.query.filter_by(
        davet_kodu=davet_kodu
    ).first()

    if not grup:

        flash(
            "Geçersiz davet kodu.",
            "danger"
        )

        return redirect(
            url_for("gruplar")
        )

    existing = GrupUyeligi.query.filter_by(
        grup_id=grup.id,
        kullanici_id=current_user.id
    ).first()

    if existing:

        flash(
            "Zaten bu grubun üyesisiniz.",
            "warning"
        )

        return redirect(
            url_for(
                "grup",
                grup_id=grup.id
            )
        )

    membership = GrupUyeligi(
        grup_id=grup.id,
        kullanici_id=current_user.id
    )

    db.session.add(
        membership
    )

    db.session.commit()

    flash(
        "Gruba katıldınız.",
        "success"
    )

    return redirect(
        url_for(
            "grup",
            grup_id=grup.id
        )
    )


# ============================================================
# GROUP DETAIL
# ============================================================

@app.route("/grup/<int:grup_id>")
@login_required
def grup(grup_id):

    grup_obj = db.session.get(
        Grup,
        grup_id
    )

    if not grup_obj:
        abort(404)

    membership = GrupUyeligi.query.filter_by(
        grup_id=grup_id,
        kullanici_id=current_user.id
    ).first()

    if not membership:
        abort(403)

    now = utc_now_naive()

    en_yakin_mac = (
        Mac.query
        .filter(
            Mac.lig_id == CHAMPIONS_LEAGUE_ID,
            Mac.baslangic.isnot(None),
            Mac.baslangic >= now
        )
        .order_by(Mac.baslangic.asc())
        .first()
    )

    hedef_hafta = en_yakin_mac.hafta if en_yakin_mac and en_yakin_mac.hafta else None

    if hedef_hafta:
        maclar = (
            Mac.query
            .filter(
                Mac.lig_id == CHAMPIONS_LEAGUE_ID,
                Mac.hafta == hedef_hafta
            )
            .order_by(Mac.baslangic.asc())
            .all()
        )
    else:
        maclar = (
            Mac.query
            .filter(Mac.lig_id == CHAMPIONS_LEAGUE_ID)
            .order_by(Mac.baslangic.desc())
            .limit(10)
            .all()
        )

    tahminler = Tahmin.query.filter_by(
        grup_id=grup_id,
        kullanici_id=current_user.id
    ).all()

    tahmin_dict = {
        t.mac_id: t
        for t in tahminler
    }

    members = (
        GrupUyeligi.query
        .filter_by(
            grup_id=grup_id
        )
        .all()
    )

    tum_grup_tahminleri = Tahmin.query.filter_by(grup_id=grup_id).all()
    
    grup_tahmin_matrisi = {}
    for t in tum_grup_tahminleri:
        if t.mac_id not in grup_tahmin_matrisi:
            grup_tahmin_matrisi[t.mac_id] = {}
        grup_tahmin_matrisi[t.mac_id][t.kullanici_id] = t

    leaderboard = []

    for member in members:

        total = (
            db.session.query(
                db.func.coalesce(
                    db.func.sum(
                        Tahmin.puan
                    ),
                    0
                )
            )
            .filter(
                Tahmin.grup_id ==
                grup_id,

                Tahmin.kullanici_id ==
                member.kullanici_id
            )
            .scalar()
            or 0
        )

        leaderboard.append(
            {
                "user":
                    member.kullanici,

                "points":
                    int(total)
            }
        )

    leaderboard.sort(
        key=lambda x: x["points"],
        reverse=True
    )

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


# ============================================================
# PREDICTION
# ============================================================

@app.route(
    "/tahmin/<int:grup_id>/<int:mac_id>",
    methods=["GET", "POST"]
)
@login_required
def tahmin(grup_id, mac_id):

    membership = GrupUyeligi.query.filter_by(
        grup_id=grup_id,
        kullanici_id=current_user.id
    ).first()

    if not membership:
        abort(403)

    mac = db.session.get(
        Mac,
        mac_id
    )

    if not mac:
        abort(404)

    if not mac.oynanabilir_mi():

        flash(
            "Bu maç için artık tahmin yapılamaz.",
            "warning"
        )

        return redirect(
            url_for(
                "grup",
                grup_id=grup_id
            )
        )

    existing = Tahmin.query.filter_by(
        grup_id=grup_id,
        mac_id=mac_id,
        kullanici_id=current_user.id
    ).first()

    if request.method == "POST":

        try:

            ev_skor = int(
                request.form.get(
                    "ev_skor"
                )
            )

            deplasman_skor = int(
                request.form.get(
                    "deplasman_skor"
                )
            )

        except Exception:

            flash(
                "Skorları doğru girin.",
                "danger"
            )

            return redirect(
                url_for(
                    "tahmin",
                    grup_id=grup_id,
                    mac_id=mac_id
                )
            )

        if (
            ev_skor < 0
            or
            deplasman_skor < 0
        ):

            flash(
                "Skor negatif olamaz.",
                "danger"
            )

            return redirect(
                url_for(
                    "tahmin",
                    grup_id=grup_id,
                    mac_id=mac_id
                )
            )

        if existing:

            existing.ev_skor = ev_skor
            existing.deplasman_skor = deplasman_skor
            existing.guncellenme = (
                datetime.utcnow()
            )

        else:

            new_prediction = Tahmin(
                grup_id=grup_id,
                mac_id=mac_id,
                kullanici_id=current_user.id,
                ev_skor=ev_skor,
                deplasman_skor=deplasman_skor,
                puan=0
            )

            db.session.add(
                new_prediction
            )

        db.session.commit()

        flash(
            "Tahmininiz kaydedildi.",
            "success"
        )

        return redirect(
            url_for(
                "grup",
                grup_id=grup_id
            )
        )

    return render_template(
        "tahmin.html",
        grup=membership.grup,
        mac=mac,
        tahmin=existing
    )


# ============================================================
# PROFILE
# ============================================================

@app.route("/profil")
@login_required
def profil():

    total_points = (
        db.session.query(
            db.func.coalesce(
                db.func.sum(
                    Tahmin.puan
                ),
                0
            )
        )
        .filter(
            Tahmin.kullanici_id ==
            current_user.id
        )
        .scalar()
        or 0
    )

    prediction_count = Tahmin.query.filter_by(
        kullanici_id=current_user.id
    ).count()

    return render_template(
        "profil.html",
        toplam_puan=total_points,
        toplam_tahmin=prediction_count
    )


# ============================================================
# ADMIN DASHBOARD
# ============================================================

@app.route("/admin")
@admin_required
def admin():

    total_users = Kullanici.query.count()

    total_groups = Grup.query.count()

    total_matches = Mac.query.count()

    total_predictions = Tahmin.query.count()

    upcoming_matches = (
        Mac.query
        .filter(
            Mac.baslangic.isnot(None),

            Mac.baslangic >
            utc_now_naive(),

            Mac.lig_id ==
            CHAMPIONS_LEAGUE_ID,

            ~Mac.durum.in_(
                [
                    "bitti",
                    "iptal",
                    "ertelendi"
                ]
            )
        )
        .count()
    )

    return render_template(
        "admin.html",

        total_users=
            total_users,

        total_groups=
            total_groups,

        total_matches=
            total_matches,

        total_predictions=
            total_predictions,

        upcoming_matches=
            upcoming_matches
    )


# ============================================================
# ADMIN SYNC
# ============================================================

@app.route(
    "/admin/sync",
    methods=["GET", "POST"]
)
@admin_required
def admin_sync():

    try:

        result = sync_champions_league()

        flash(
            f"Senkronizasyon tamamlandı. "
            f"API: {result['api_matches']} | "
            f"Yeni: {result['inserted']} | "
            f"Güncellenen: {result['updated']} | "
            f"DB: {result['db_total_matches']} | "
            f"Yaklaşan: {result['upcoming_matches']}",
            "success"
        )

    except Exception as e:

        db.session.rollback()

        flash(
            f"Senkronizasyon hatası: {e}",
            "danger"
        )

    return redirect(
        url_for("admin")
    )


# ============================================================
# ADMIN API TEST
# ============================================================

@app.route("/admin/api-test")
@admin_required
def admin_api_test():

    try:

        info = football_data_get(
            f"competitions/{CHAMPIONS_LEAGUE_CODE}"
        )

        return jsonify(
            {
                "success": True,
                "competition": info.get(
                    "name"
                ),
                "id": info.get(
                    "id"
                ),
                "code": info.get(
                    "code"
                ),
                "currentSeason":
                    info.get(
                        "currentSeason"
                    )
            }
        )

    except Exception as e:

        return jsonify(
            {
                "success": False,
                "error": str(e)
            }
        ), 500


# ============================================================
# ADMIN STATUS
# ============================================================

@app.route("/admin/durum")
@admin_required
def admin_durum():

    total_matches = Mac.query.count()

    upcoming_matches = (
        Mac.query
        .filter(
            Mac.baslangic.isnot(None),

            Mac.baslangic >
            utc_now_naive(),

            Mac.lig_id ==
            CHAMPIONS_LEAGUE_ID,

            ~Mac.durum.in_(
                [
                    "bitti",
                    "iptal",
                    "ertelendi"
                ]
            )
        )
        .count()
    )

    finished_matches = (
        Mac.query
        .filter(
            Mac.durum ==
            "bitti"
        )
        .count()
    )

    planned_matches = (
        Mac.query
        .filter(
            Mac.durum ==
            "planlandi"
        )
        .count()
    )

    seasons = [
        row[0]
        for row in (
            db.session.query(
                Mac.sezon
            )
            .filter(
                Mac.sezon.isnot(None)
            )
            .distinct()
            .order_by(
                Mac.sezon.desc()
            )
            .all()
        )
    ]

    statuses = {}

    rows = (
        db.session.query(
            Mac.durum,
            db.func.count(Mac.id)
        )
        .group_by(
            Mac.durum
        )
        .all()
    )

    for status, count in rows:
        statuses[status] = count

    return jsonify(
        {
            "total_matches":
                total_matches,

            "upcoming_matches":
                upcoming_matches,

            "finished_matches":
                finished_matches,

            "planned_matches":
                planned_matches,

            "seasons":
                seasons,

            "statuses":
                statuses,

            "competition_id":
                CHAMPIONS_LEAGUE_ID
        }
    )


# ============================================================
# ADMIN ALL MATCHES
# ============================================================

@app.route("/admin/maclar")
@admin_required
def admin_maclar():

    maclar = (
        Mac.query
        .order_by(
            Mac.baslangic.asc()
        )
        .all()
    )

    return jsonify(
        [
            {
                "id": mac.id,

                "external_id":
                    mac.external_id,

                "home":
                    mac.ev_sahibi,

                "away":
                    mac.deplasman,

                "date":
                    (
                        mac.baslangic.isoformat()
                        if mac.baslangic
                        else None
                    ),

                "season":
                    mac.sezon,

                "competition_id":
                    mac.lig_id,

                "status":
                    mac.durum,

                "api_status":
                    mac.api_status,

                "home_score":
                    mac.ev_skor,

                "away_score":
                    mac.deplasman_skor
            }

            for mac in maclar
        ]
    )


# ============================================================
# ADMIN SYNC JSON
# ============================================================

@app.route("/admin/sync-json")
@admin_required
def admin_sync_json():

    try:

        result = sync_champions_league()

        return jsonify(result)

    except Exception as e:

        db.session.rollback()

        return jsonify(
            {
                "success": False,
                "error": str(e)
            }
        ), 500


# ============================================================
# ERROR HANDLERS
# ============================================================

@app.errorhandler(403)
def forbidden(error):

    return """
    <h1>403</h1>
    <p>Bu sayfaya erişim yetkiniz yok.</p>
    """, 403


@app.errorhandler(404)
def not_found(error):

    return """
    <h1>404</h1>
    <p>Sayfa bulunamadı.</p>
    """, 404


@app.errorhandler(500)
def internal_error(error):

    db.session.rollback()

    return """
    <h1>500</h1>
    <p>Sunucu tarafında bir hata oluştu.</p>
    """, 500


# ============================================================
# DATABASE INITIALIZATION
# ============================================================

def initialize_database():

    with app.app_context():

        db.create_all()

        admin_username = os.getenv(
            "ADMIN_USERNAME",
            "admin"
        )

        admin_password = os.getenv(
            "ADMIN_PASSWORD",
            "Admin123!"
        )

        admin_user = Kullanici.query.filter_by(
            kullanici_adi=admin_username
        ).first()

        if not admin_user:

            admin_user = Kullanici(
                kullanici_adi=
                    admin_username,
                admin=True
            )

            admin_user.set_password(
                admin_password
            )

            db.session.add(
                admin_user
            )

            db.session.commit()

        else:

            if not admin_user.admin:

                admin_user.admin = True

                db.session.commit()


# ============================================================
# BACKGROUND SYNC
# ============================================================

def background_sync():

    time.sleep(10)

    while True:

        try:

            with app.app_context():
                sync_champions_league()

        except Exception as e:

            with app.app_context():

                db.session.rollback()

        time.sleep(
            SYNC_INTERVAL_MINUTES * 60
        )


# ============================================================
# STARTUP SYNC
# ============================================================

def startup_sync():

    try:

        with app.app_context():
            sync_champions_league()

    except Exception as e:

        with app.app_context():

            db.session.rollback()


# ============================================================
# RUN
# ============================================================

if __name__ == "__main__":

    initialize_database()

    if FOOTBALL_DATA_TOKEN:

        startup_sync()

        sync_thread = threading.Thread(
            target=background_sync,
            daemon=True
        )

        sync_thread.start()

    app.run(
        host="127.0.0.1",
        port=5000,
        debug=False,
        threaded=True
    )