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
    base = {
        "id":           annonce_hash(source, url),
        "source":       source,
        "recherche_id": recherche,
        "type_bien":    "appartement",
        "titre":        f"Studio test {n}",
        "prix":         80_000 + n * 10_000,   # écart 10k→empreinte unique
        "surface":      20.0 + n * 5,             # écart 5m²→empreinte unique
        "ville":        "Grenoble",
        "url":          url,
        "description":  f"Description {n}",
        **kwargs,
    }
    # Calcule l'empreinte cross-source automatiquement
    from core.collectors.base import empreinte_bien as _emp
    if base.get("empreinte") is None:
        base["empreinte"] = _emp(
            base.get("ville"), base.get("surface"),
            base.get("prix"), base.get("nb_pieces")
        )
    return base


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




class TestDeduplicationCrossSource:
    def test_meme_bien_deux_sources(self, db):
        """Même logement sur LBC et Bien'ici → une seule entrée en DB."""
        a_lbc = _annonce(1, source="leboncoin",
                         prix=85000, surface=22.0, ville="Grenoble", nb_pieces=1)
        a_bienici = {
            **a_lbc,
            "id":     annonce_hash("bienici", "https://bienici.com/studio-999"),
            "source": "bienici",
            "url":    "https://bienici.com/studio-999",
            # même empreinte car même ville+surface+prix+pièces
        }
        assert db.inserer(a_lbc)    is True,  "LBC doit être inséré"
        assert db.inserer(a_bienici) is False, "Doublon cross-source doit être bloqué"
        assert sum(db.stats().values()) == 1

    def test_meme_bien_trois_sources(self, db):
        """Même bien sur LBC, Bien'ici et PAP → une seule entrée."""
        base = {"prix": 90000, "surface": 25.0, "ville": "Grenoble", "nb_pieces": 2}
        sources = [
            ("leboncoin", "https://lbc.fr/1"),
            ("bienici",   "https://bienici.com/1"),
            ("pap",       "https://pap.fr/1"),
        ]
        resultats = []
        for source, url in sources:
            a = {**_annonce(1, source=source), **base,
                 "id": annonce_hash(source, url), "url": url}
            from core.collectors.base import empreinte_bien
            a["empreinte"] = empreinte_bien(
                base["ville"], base["surface"], base["prix"], base["nb_pieces"]
            )
            resultats.append(db.inserer(a))
        assert resultats == [True, False, False], (
            f"Seul le premier doit être inséré, résultats: {resultats}"
        )

    def test_meme_bien_jours_differents(self, db):
        """Annonce toujours active le lendemain → non réinsérée."""
        a = _annonce(1, source="leboncoin", prix=85000, surface=22.0, nb_pieces=1)
        db.inserer(a)
        # Simuler J+1 : même annonce, URL identique
        assert db.inserer(a) is False, "Réinsertion le lendemain doit être bloquée"

    def test_biens_differents_non_bloques(self, db):
        """Deux biens différents de la même source → tous les deux insérés."""
        a1 = _annonce(1, source="leboncoin", prix=85000, surface=22.0, nb_pieces=1)
        a2 = _annonce(2, source="leboncoin", prix=120000, surface=35.0, nb_pieces=2)
        assert db.inserer(a1) is True
        assert db.inserer(a2) is True
        assert sum(db.stats().values()) == 2

    def test_sans_empreinte_pas_bloque(self, db):
        """Annonce sans prix/surface → empreinte None → pas de blocage."""
        a1 = {**_annonce(1), "prix": None, "surface": None, "empreinte": None}
        a2 = {**_annonce(2), "prix": None, "surface": None, "empreinte": None}
        assert db.inserer(a1) is True
        assert db.inserer(a2) is True  # empreinte None → pas de dédup cross-source

    def test_empreinte_tolerante_surface(self, db):
        """Surface 22 m² vs 22.3 m² → même empreinte → doublon détecté."""
        from core.collectors.base import empreinte_bien
        a1 = {**_annonce(1, source="lbc"),
              "prix": 85000, "surface": 22.0,
              "empreinte": empreinte_bien("Grenoble", 22.0, 85000, 1)}
        a2 = {**_annonce(2, source="bienici"),
              "prix": 85000, "surface": 22.3,   # légèrement différent
              "empreinte": empreinte_bien("Grenoble", 22.3, 85000, 1)}
        assert a1["empreinte"] == a2["empreinte"], "Les empreintes doivent être égales"
        db.inserer(a1)
        assert db.inserer(a2) is False

    def test_empreinte_stricte_pieces(self, db):
        """T1 vs T2 → empreintes différentes → tous les deux insérés."""
        from core.collectors.base import empreinte_bien
        a1 = {**_annonce(1), "prix": 85000, "surface": 30.0, "nb_pieces": 1,
              "empreinte": empreinte_bien("Grenoble", 30.0, 85000, 1)}
        a2 = {**_annonce(2), "prix": 85000, "surface": 30.0, "nb_pieces": 2,
              "empreinte": empreinte_bien("Grenoble", 30.0, 85000, 2)}
        assert a1["empreinte"] != a2["empreinte"]
        assert db.inserer(a1) is True
        assert db.inserer(a2) is True

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
