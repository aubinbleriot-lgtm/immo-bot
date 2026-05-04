"""Tests unitaires — ImmoDB (SQLite thread-safe)."""

import json
import pathlib
import tempfile
import threading

import pytest

from core.database import ImmoDB, annonce_hash


@pytest.fixture
def db(tmp_path):
    d = ImmoDB(tmp_path / "test.db")
    yield d
    d.close()


def _annonce(n=1, source="lbc", recherche="locatif_grenoble", **kwargs):
    url = f"https://example.com/{n}"
    return {
        "id":           annonce_hash(source, url),
        "source":       source,
        "recherche_id": recherche,
        "type_bien":    "appartement",
        "titre":        f"Studio test {n}",
        "prix":         80_000 + n * 1000,
        "surface":      20.0 + n,
        "ville":        "Grenoble",
        "url":          url,
        "description":  f"Description {n}",
        **kwargs,
    }


class TestInsertion:
    def test_insere_nouvelle(self, db):
        assert db.inserer(_annonce(1)) is True

    def test_dedoublonnage(self, db):
        a = _annonce(1)
        db.inserer(a)
        assert db.inserer(a) is False

    def test_hash_stable(self):
        h1 = annonce_hash("lbc", "https://example.com/123")
        h2 = annonce_hash("lbc", "https://example.com/123")
        assert h1 == h2 == annonce_hash("lbc", "https://example.com/123")

    def test_hash_different_sources(self):
        h1 = annonce_hash("lbc",     "https://example.com/1")
        h2 = annonce_hash("bienici", "https://example.com/1")
        assert h1 != h2

    def test_prix_m2_calcule(self, db):
        db.inserer(_annonce(1, prix=100_000, surface=25.0))
        row = db.a_scorer(limite=1)[0]
        assert row["prix_m2"] == 4000.0


class TestEnrichissement:
    def test_mettre_a_jour_geo(self, db):
        db.inserer(_annonce(1))
        ann = db.a_scorer(1)[0]
        db.mettre_a_jour_geo(ann["id"], {
            "dist_campus_km":  0.8,
            "campus_proche":   "UGA",
            "dist_gare_km":    1.2,
            "risque_geo":      "RAS",
            "loyer_estime":    300,
            "rendement_brut":  4.5,
            "rendement_net":   3.15,
        })
        db.marquer_statut(ann["id"], "enrichi")
        row = db.a_scorer(1)[0]
        assert row["dist_campus_km"] == 0.8
        assert row["rendement_brut"] == 4.5
        assert row["statut"] == "enrichi"


class TestScoring:
    def test_mettre_a_jour_score(self, db):
        db.inserer(_annonce(1))
        ann = db.a_scorer(1)[0]
        db.mettre_a_jour_score(ann["id"], {
            "score_a": 45, "score_b": 72, "score_final": 72,
            "verdict": "TRÈS INTÉRESSANT",
            "points_forts": ["Proche campus", "Bon DPE"],
            "points_vigilance": ["Charges élevées"],
            "questions": ["Montant charges ?"],
            "resume_ia": "Bonne opportunité locative.",
        })
        top = db.top_du_jour(seuil=70)
        assert len(top) == 1
        assert top[0]["score_final"] == 72
        assert top[0]["verdict"] == "TRÈS INTÉRESSANT"
        pf = json.loads(top[0]["points_forts"])
        assert "Proche campus" in pf

    def test_a_alerter_seuil(self, db):
        for i in range(3):
            db.inserer(_annonce(i+1))
            ann = db.a_scorer(1)[0]
            db.mettre_a_jour_score(ann["id"], {
                "score_a": 0, "score_b": 60 + i*10, "score_final": 60 + i*10,
                "verdict": "À SURVEILLER", "points_forts": [],
                "points_vigilance": [], "questions": [], "resume_ia": "",
            })
        alertes = db.a_alerter(seuil=75)
        assert len(alertes) == 1
        assert alertes[0]["score_final"] == 80

    def test_marquer_alerte(self, db):
        db.inserer(_annonce(1))
        ann = db.a_scorer(1)[0]
        db.mettre_a_jour_score(ann["id"], {
            "score_a": 0, "score_b": 80, "score_final": 80,
            "verdict": "PÉPITE", "points_forts": [], "points_vigilance": [],
            "questions": [], "resume_ia": "",
        })
        db.marquer_alerte(ann["id"])
        assert db.a_alerter(seuil=75) == []  # déjà alerté


class TestStats:
    def test_stats_vide(self, db):
        assert db.stats() == {}

    def test_stats_sources(self, db):
        db.inserer(_annonce(1, source="lbc"))
        db.inserer(_annonce(2, source="lbc"))
        db.inserer(_annonce(3, source="bienici"))
        s = db.stats_sources()
        assert s["lbc"] == 2
        assert s["bienici"] == 1

    def test_log_run(self, db):
        db.log_run({
            "source": "lbc", "nb_collectes": 10, "nb_nouvelles": 5,
            "nb_scorees": 3, "nb_alertes": 1, "duree_sec": 42.5,
        })
        # Pas d'exception = succès


class TestThreadSafety:
    def test_insertions_concurrentes(self, tmp_path):
        """Vérifie qu'on peut insérer depuis plusieurs threads sans corruption."""
        db = ImmoDB(tmp_path / "concurrent.db")
        errors = []

        def inserer_batch(start):
            try:
                for i in range(start, start + 10):
                    db.inserer(_annonce(i, source=f"src_{start}"))
            except Exception as e:
                errors.append(str(e))

        threads = [threading.Thread(target=inserer_batch, args=(i*10,)) for i in range(4)]
        for t in threads: t.start()
        for t in threads: t.join()

        assert errors == [], f"Erreurs thread-safety : {errors}"
        sources = db.stats_sources()
        total = sum(sources.values())
        assert total == 40
        db.close()
