"""
Base de données SQLite — persistée dans le repo Git.
Thread-safety : WAL mode + une connexion par thread via threading.local().
"""

import hashlib
import json
import logging
import sqlite3
import threading
from datetime import datetime
from pathlib import Path

log = logging.getLogger("database")

SCHEMA = """
PRAGMA journal_mode=WAL;
PRAGMA synchronous=NORMAL;

CREATE TABLE IF NOT EXISTS annonces (
    id              TEXT PRIMARY KEY,
    source          TEXT NOT NULL,
    recherche_id    TEXT NOT NULL,
    type_bien       TEXT,
    titre           TEXT NOT NULL,
    prix            INTEGER,
    surface         REAL,
    prix_m2         REAL,
    ville           TEXT,
    code_postal     TEXT,
    adresse         TEXT,
    lat             REAL,
    lng             REAL,
    url             TEXT NOT NULL,
    description     TEXT,
    nb_pieces       INTEGER,
    nb_chambres     INTEGER,
    dpe             TEXT,
    ges             TEXT,
    charges         INTEGER,
    date_publiee    TEXT,
    date_vue        TEXT NOT NULL,

    -- Enrichissement géo
    dist_campus_km  REAL,
    campus_proche   TEXT,
    dist_gare_km    REAL,
    risque_geo      TEXT,

    -- Calcul financier
    loyer_estime    INTEGER,
    rendement_brut  REAL,
    rendement_net   REAL,

    -- Scoring IA (Gemini)
    score_a         INTEGER,
    score_b         INTEGER,
    score_final     INTEGER,
    verdict         TEXT,
    points_forts    TEXT,
    points_vigilance TEXT,
    questions       TEXT,
    resume_ia       TEXT,

    -- Suivi
    statut          TEXT DEFAULT 'nouveau',
    alerte_envoyee  INTEGER DEFAULT 0,
    notes           TEXT,
    date_modif      TEXT
);

CREATE INDEX IF NOT EXISTS idx_statut    ON annonces(statut);
CREATE INDEX IF NOT EXISTS idx_score     ON annonces(score_final);
CREATE INDEX IF NOT EXISTS idx_date_vue  ON annonces(date_vue);
CREATE INDEX IF NOT EXISTS idx_source    ON annonces(source);
CREATE INDEX IF NOT EXISTS idx_recherche ON annonces(recherche_id);

CREATE TABLE IF NOT EXISTS runs (
    id           INTEGER PRIMARY KEY AUTOINCREMENT,
    date_run     TEXT NOT NULL,
    source       TEXT,
    nb_collectes  INTEGER DEFAULT 0,
    nb_nouvelles  INTEGER DEFAULT 0,
    nb_scorees    INTEGER DEFAULT 0,
    nb_alertes    INTEGER DEFAULT 0,
    duree_sec    REAL,
    erreur       TEXT
);
"""


def annonce_hash(source: str, url: str) -> str:
    s = f"{source}|{url}".encode("utf-8")
    return hashlib.sha256(s).hexdigest()[:20]


class ImmoDB:
    """
    Thread-safe SQLite via threading.local() — une connexion par thread.
    WAL mode pour les écritures concurrentes.
    """

    def __init__(self, path: Path):
        self.path = path
        self._local = threading.local()
        # Initialiser le schéma sur la connexion principale
        conn = self._conn()
        conn.executescript(SCHEMA)
        conn.commit()

    def _conn(self) -> sqlite3.Connection:
        if not hasattr(self._local, "conn") or self._local.conn is None:
            conn = sqlite3.connect(str(self.path), timeout=30)
            conn.row_factory = sqlite3.Row
            conn.execute("PRAGMA journal_mode=WAL")
            conn.execute("PRAGMA synchronous=NORMAL")
            self._local.conn = conn
        return self._local.conn

    def close(self):
        if hasattr(self._local, "conn") and self._local.conn:
            self._local.conn.close()
            self._local.conn = None

    # ── Existence ─────────────────────────────────────────────────────────
    def existe(self, annonce_id: str) -> bool:
        cur = self._conn().execute("SELECT 1 FROM annonces WHERE id=?", (annonce_id,))
        return cur.fetchone() is not None

    # ── Insertion ─────────────────────────────────────────────────────────
    def inserer(self, a: dict) -> bool:
        if self.existe(a["id"]):
            return False
        now = datetime.now().isoformat()
        prix   = a.get("prix")
        surf   = a.get("surface")
        prix_m2 = round(prix / surf) if prix and surf and surf > 0 else None
        params = {
            "id": a["id"], "source": a["source"],
            "recherche_id": a.get("recherche_id",""),
            "type_bien": a.get("type_bien"),
            "titre": a["titre"],
            "prix": a.get("prix"), "surface": a.get("surface"), "prix_m2": prix_m2,
            "ville": a.get("ville"), "code_postal": a.get("code_postal"),
            "adresse": a.get("adresse"), "lat": a.get("lat"), "lng": a.get("lng"),
            "url": a["url"], "description": a.get("description",""),
            "nb_pieces": a.get("nb_pieces"), "nb_chambres": a.get("nb_chambres"),
            "dpe": a.get("dpe"), "ges": a.get("ges"), "charges": a.get("charges"),
            "date_publiee": a.get("date_publiee"),
            "date_vue": now, "date_modif": now,
        }
        self._conn().execute("""
            INSERT OR IGNORE INTO annonces (
                id, source, recherche_id, type_bien, titre, prix, surface, prix_m2,
                ville, code_postal, adresse, lat, lng, url, description,
                nb_pieces, nb_chambres, dpe, ges, charges,
                date_publiee, date_vue, statut, date_modif
            ) VALUES (
                :id,:source,:recherche_id,:type_bien,:titre,:prix,:surface,:prix_m2,
                :ville,:code_postal,:adresse,:lat,:lng,:url,:description,
                :nb_pieces,:nb_chambres,:dpe,:ges,:charges,
                :date_publiee,:date_vue,'nouveau',:date_modif
            )""", params,
        )
        self._conn().commit()
        return True

    # ── Mise à jour enrichissement géo ────────────────────────────────────
    def mettre_a_jour_geo(self, annonce_id: str, geo: dict) -> None:
        self._conn().execute("""
            UPDATE annonces SET
                dist_campus_km=:dist_campus_km,
                campus_proche=:campus_proche,
                dist_gare_km=:dist_gare_km,
                risque_geo=:risque_geo,
                loyer_estime=:loyer_estime,
                rendement_brut=:rendement_brut,
                rendement_net=:rendement_net,
                date_modif=:now
            WHERE id=:id""",
            {**geo, "id": annonce_id, "now": datetime.now().isoformat()},
        )
        self._conn().commit()

    # ── Mise à jour scoring ───────────────────────────────────────────────
    def mettre_a_jour_score(self, annonce_id: str, s: dict) -> None:
        self._conn().execute("""
            UPDATE annonces SET
                score_a=:score_a, score_b=:score_b, score_final=:score_final,
                verdict=:verdict,
                points_forts=:points_forts, points_vigilance=:points_vigilance,
                questions=:questions, resume_ia=:resume_ia,
                statut='score', date_modif=:now
            WHERE id=:id""",
            {
                "id":             annonce_id,
                "score_a":        s.get("score_a"),
                "score_b":        s.get("score_b"),
                "score_final":    s.get("score_final"),
                "verdict":        s.get("verdict"),
                "points_forts":   json.dumps(s.get("points_forts", []), ensure_ascii=False),
                "points_vigilance": json.dumps(s.get("points_vigilance", []), ensure_ascii=False),
                "questions":      json.dumps(s.get("questions", []), ensure_ascii=False),
                "resume_ia":      s.get("resume_ia", ""),
                "now":            datetime.now().isoformat(),
            },
        )
        self._conn().commit()

    def marquer_alerte(self, annonce_id: str) -> None:
        self._conn().execute(
            "UPDATE annonces SET alerte_envoyee=1, statut='alerte', date_modif=? WHERE id=?",
            (datetime.now().isoformat(), annonce_id),
        )
        self._conn().commit()

    def marquer_statut(self, annonce_id: str, statut: str, notes: str = "") -> None:
        self._conn().execute(
            "UPDATE annonces SET statut=?, notes=?, date_modif=? WHERE id=?",
            (statut, notes, datetime.now().isoformat(), annonce_id),
        )
        self._conn().commit()

    # ── Requêtes ──────────────────────────────────────────────────────────
    def a_enrichir(self, limite: int = 50) -> list:
        cur = self._conn().execute(
            "SELECT * FROM annonces WHERE statut='nouveau' ORDER BY date_vue DESC LIMIT ?",
            (limite,),
        )
        return [dict(r) for r in cur.fetchall()]

    def a_scorer(self, limite: int = 30) -> list:
        cur = self._conn().execute(
            """SELECT * FROM annonces
               WHERE statut IN ('nouveau','enrichi')
               ORDER BY date_vue DESC LIMIT ?""",
            (limite,),
        )
        return [dict(r) for r in cur.fetchall()]

    def a_alerter(self, seuil: int = 75) -> list:
        cur = self._conn().execute(
            "SELECT * FROM annonces WHERE score_final>=? AND alerte_envoyee=0 ORDER BY score_final DESC",
            (seuil,),
        )
        return [dict(r) for r in cur.fetchall()]

    def top_du_jour(self, seuil: int = 60, limite: int = 20) -> list:
        today = datetime.now().date().isoformat()
        cur = self._conn().execute(
            """SELECT * FROM annonces
               WHERE score_final>=? AND date(date_vue)=?
               ORDER BY score_final DESC LIMIT ?""",
            (seuil, today, limite),
        )
        return [dict(r) for r in cur.fetchall()]

    def toutes(self, limite: int = 200, offset: int = 0) -> list:
        cur = self._conn().execute(
            "SELECT * FROM annonces ORDER BY date_vue DESC LIMIT ? OFFSET ?",
            (limite, offset),
        )
        return [dict(r) for r in cur.fetchall()]

    def stats(self) -> dict:
        cur = self._conn().execute("SELECT statut, COUNT(*) n FROM annonces GROUP BY statut")
        return {r["statut"]: r["n"] for r in cur.fetchall()}

    def stats_sources(self) -> dict:
        cur = self._conn().execute(
            "SELECT source, COUNT(*) n FROM annonces GROUP BY source ORDER BY n DESC"
        )
        return {r["source"]: r["n"] for r in cur.fetchall()}

    def log_run(self, run: dict) -> None:
        self._conn().execute("""
            INSERT INTO runs (date_run,source,nb_collectes,nb_nouvelles,nb_scorees,nb_alertes,duree_sec,erreur)
            VALUES (?,?,?,?,?,?,?,?)""",
            (
                run.get("date_run", datetime.now().isoformat()),
                run.get("source", "all"),
                run.get("nb_collectes", 0), run.get("nb_nouvelles", 0),
                run.get("nb_scorees", 0),  run.get("nb_alertes", 0),
                run.get("duree_sec"),       run.get("erreur"),
            ),
        )
        self._conn().commit()
