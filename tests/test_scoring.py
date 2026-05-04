"""Tests unitaires — moteur de scoring hybride."""

import pytest
import types as _types

from core.scorer import (
    score_plan_a, score_plan_b,
    _score_dpe, _score_rendement, _score_prix_marche,
    _score_campus, _score_risques, _score_tension_locative,
    _verdict_auto, scorer_annonce,
)


@pytest.fixture
def annonce_locatif():
    return {
        "id": "test_001", "source": "lbc",
        "recherche_id": "locatif_grenoble",
        "type_bien": "appartement", "titre": "Studio centre Grenoble",
        "prix": 85_000, "surface": 22, "prix_m2": 3863,
        "ville": "Grenoble", "dpe": "C",
        "dist_campus_km": 0.8, "campus_proche": "UGA",
        "rendement_brut": 6.8, "rendement_net": 4.76,
        "risque_geo": "RAS", "description": "Beau studio proche campus.",
    }


@pytest.fixture
def annonce_residence():
    return {
        "id": "test_002", "source": "lbc",
        "recherche_id": "residence_isere",
        "type_bien": "maison", "titre": "Maison avec jardin Allevard",
        "prix": 280_000, "surface": 110, "prix_m2": 2545,
        "ville": "Allevard", "dpe": "D",
        "dist_campus_km": 28.0, "campus_proche": "UGA",
        "rendement_brut": None, "rendement_net": None,
        "risque_geo": "Séisme faible",
        "description": "Belle maison avec grand terrain, calme.",
    }


class TestScoresDPE:
    @pytest.mark.parametrize("dpe,expected", [
        ("A", 10), ("B", 9), ("C", 7), ("D", 5),
        ("E", 3), ("F", 1), ("G", 0), (None, 4), ("", 4),
    ])
    def test_score_dpe(self, dpe, expected):
        assert _score_dpe(dpe) == expected

    def test_dpe_case_insensitive(self):
        assert _score_dpe("c") == _score_dpe("C") == 7


class TestScoresRendement:
    @pytest.mark.parametrize("rdt,expected", [
        (8.5, 20), (7.0, 15), (5.5, 10), (3.5, 5), (2.0, 0), (None, 0),
    ])
    def test_score_rendement(self, rdt, expected):
        assert _score_rendement(rdt) == expected


class TestScoresPrixMarche:
    def test_sous_marche_20pct(self):
        # prix_m2 = 2500 < 80% de 3200 → 15 pts
        assert _score_prix_marche(None, 2500, "Grenoble", "appartement") == 15

    def test_sous_marche_10pct(self):
        # prix_m2 = 2900 → ratio 0.906 → entre 0.90 et 1.00 → 9 pts
        score = _score_prix_marche(None, 2900, "Grenoble", "appartement")
        assert score == 9

    def test_au_marche(self):
        # prix_m2 = 3200 = médiane exacte → ratio 1.0 → entre 1.00 et 1.10 → 6 pts
        score = _score_prix_marche(None, 3200, "Grenoble", "appartement")
        assert score == 6

    def test_sur_marche_20pct(self):
        # prix_m2 = 4000 → ratio 1.25 → 0 pts
        assert _score_prix_marche(None, 4000, "Grenoble", "appartement") == 0

    def test_prix_m2_inconnu(self):
        # prix_m2 None → 5 pts (neutre)
        assert _score_prix_marche(None, None, "Grenoble", "appartement") == 5

    def test_ville_inconnue(self):
        score = _score_prix_marche(None, 2000, "VilleInconnue", "appartement")
        assert 0 <= score <= 15


class TestScoresCampus:
    @pytest.mark.parametrize("dist,expected", [
        (0.3, 15), (0.4, 15),
        (0.8, 12), (1.0, 12),
        (1.5, 9),  (2.0, 9),
        (2.5, 6),  (3.5, 6),
        (4.0, 3),  (5.5, 3),
        (10.0, 0), (None, 5),
    ])
    def test_score_campus(self, dist, expected):
        assert _score_campus(dist) == expected


class TestScoresRisques:
    def test_ras(self):
        assert _score_risques("RAS") == 10

    def test_aucun_risque(self):
        assert _score_risques(None) == 10

    def test_inondation(self):
        assert _score_risques("Inondation") == 2

    def test_seisme(self):
        assert _score_risques("Séisme faible") == 5

    def test_risque_inconnu(self):
        score = _score_risques("Retrait-gonflement argile")
        assert 0 <= score <= 10


class TestPlanB:
    def test_score_plan_b_range(self, annonce_locatif):
        score = score_plan_b(annonce_locatif)
        assert 0 <= score <= 90

    def test_bon_locatif_score_eleve(self, annonce_locatif):
        """Studio proche campus, bon rendement → score > 50."""
        score = score_plan_b(annonce_locatif)
        assert score >= 50, f"Score trop bas pour un bon locatif : {score}"

    def test_mauvais_locatif_score_bas(self):
        annonce = {
            "prix": 200_000, "surface": 20, "prix_m2": 10_000,
            "ville": "VilleInconnue", "type_bien": "appartement",
            "dpe": "G", "dist_campus_km": 15.0,
            "rendement_brut": 1.5, "risque_geo": "Inondation",
            "recherche_id": "locatif_test",
        }
        score = score_plan_b(annonce)
        assert score <= 30, f"Score trop élevé pour un mauvais locatif : {score}"


class TestPlanA:
    def test_score_plan_a_range(self, annonce_residence):
        score = score_plan_a(annonce_residence)
        assert 0 <= score <= 30

    def test_bonne_residence_score_correct(self, annonce_residence):
        score = score_plan_a(annonce_residence)
        assert score >= 5


class TestVerdictAuto:
    @pytest.mark.parametrize("score,verdict", [
        (90, "PÉPITE"), (85, "PÉPITE"),
        (75, "TRÈS INTÉRESSANT"), (70, "TRÈS INTÉRESSANT"),
        (60, "À SURVEILLER"), (55, "À SURVEILLER"),
        (45, "MOYEN"), (40, "MOYEN"),
        (39, "À ÉVITER"), (0, "À ÉVITER"),
    ])
    def test_verdict_auto(self, score, verdict):
        assert _verdict_auto(score) == verdict


@pytest.fixture
def settings_mock():
    """Settings mock sans clé API → pas d'appel LLM, bonus Gemini = valeurs par défaut."""
    s = _types.SimpleNamespace()
    s.GROQ_API_KEY       = ""
    s.OPENROUTER_API_KEY = ""
    s.GEMINI_API_KEY     = ""
    return s


class TestScorerAnnonceSansGemini:
    def test_locatif_retourne_score_b(self, annonce_locatif, settings_mock):
        result = scorer_annonce(settings_mock, annonce_locatif)
        assert result["score_final"] == result["score_b"]
        assert 0 <= result["score_final"] <= 100

    def test_residence_retourne_score_a(self, annonce_residence, settings_mock):
        result = scorer_annonce(settings_mock, annonce_residence)
        assert result["score_final"] == result["score_a"]
        assert 0 <= result["score_final"] <= 100

    def test_structure_retour(self, annonce_locatif, settings_mock):
        result = scorer_annonce(settings_mock, annonce_locatif)
        for key in ("score_a", "score_b", "score_final", "verdict",
                    "points_forts", "points_vigilance", "questions", "resume_ia"):
            assert key in result, f"Clé manquante : {key}"

    def test_sans_prix(self, settings_mock):
        annonce = {"id": "x", "source": "lbc", "recherche_id": "locatif_grenoble",
                   "titre": "Test", "url": "https://x.com"}
        result = scorer_annonce(settings_mock, annonce)
        assert isinstance(result["score_final"], int)
