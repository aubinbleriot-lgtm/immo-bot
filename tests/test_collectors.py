"""Tests unitaires — collecteurs (normalisation, hash, structure)."""

import pytest
from core.collectors.base import (
    normaliser_annonce, annonce_hash, _to_int, _to_float,
)
from core.database import annonce_hash as db_hash


RECHERCHE = {
    "id": "locatif_grenoble", "type": "locatif",
    "ville": "Grenoble", "lat": 45.1875, "lng": 5.7358,
    "rayon_km": 5, "prix_min": 50000, "prix_max": 150000,
    "surface_min": 15, "surface_max": 40,
    "types_bien": ["appartement"],
}


class TestNormalisation:
    def test_champs_obligatoires(self):
        raw = {"url": "https://lbc.fr/123", "titre": "Studio"}
        norm = normaliser_annonce(raw, "lbc", RECHERCHE)
        assert norm["id"]
        assert norm["source"] == "lbc"
        assert norm["recherche_id"] == "locatif_grenoble"
        assert norm["url"] == "https://lbc.fr/123"

    def test_titre_tronque(self):
        raw = {"url": "https://lbc.fr/1", "titre": "A" * 600}
        norm = normaliser_annonce(raw, "lbc", RECHERCHE)
        assert len(norm["titre"]) == 500

    def test_description_tronquee(self):
        raw = {"url": "https://lbc.fr/1", "titre": "X", "description": "B" * 6000}
        norm = normaliser_annonce(raw, "lbc", RECHERCHE)
        assert len(norm["description"]) == 5000

    def test_ville_fallback_recherche(self):
        raw = {"url": "https://lbc.fr/1", "titre": "X"}
        norm = normaliser_annonce(raw, "lbc", RECHERCHE)
        assert norm["ville"] == "Grenoble"

    def test_champs_manquants_none(self):
        raw = {"url": "https://lbc.fr/1", "titre": "X"}
        norm = normaliser_annonce(raw, "lbc", RECHERCHE)
        assert norm["prix"] is None
        assert norm["surface"] is None
        assert norm["dpe"] is None

    def test_prix_converti(self):
        raw = {"url": "https://lbc.fr/1", "titre": "X", "prix": "85 000"}
        norm = normaliser_annonce(raw, "lbc", RECHERCHE)
        assert norm["prix"] == 85000

    def test_surface_float(self):
        raw = {"url": "https://lbc.fr/1", "titre": "X", "surface": "22,5"}
        norm = normaliser_annonce(raw, "lbc", RECHERCHE)
        assert norm["surface"] == 22.5


class TestHash:
    def test_deterministe(self):
        h1 = db_hash("lbc", "https://lbc.fr/123")
        h2 = db_hash("lbc", "https://lbc.fr/123")
        assert h1 == h2

    def test_different_url(self):
        h1 = db_hash("lbc", "https://lbc.fr/1")
        h2 = db_hash("lbc", "https://lbc.fr/2")
        assert h1 != h2

    def test_different_source(self):
        h1 = db_hash("lbc",     "https://lbc.fr/1")
        h2 = db_hash("bienici", "https://lbc.fr/1")
        assert h1 != h2

    def test_longueur_20(self):
        assert len(db_hash("lbc", "https://lbc.fr/1")) == 20


class TestToInt:
    @pytest.mark.parametrize("val,expected", [
        ("85 000", 85000), ("85\u202f000", 85000),
        (85000, 85000), (85000.9, 85000),
        ("", None), (None, None), ("N/A", None),
    ])
    def test_to_int(self, val, expected):
        assert _to_int(val) == expected


class TestToFloat:
    @pytest.mark.parametrize("val,expected", [
        ("22.5", 22.5), ("22,5", 22.5),
        (22.5, 22.5), ("", None), (None, None),
    ])
    def test_to_float(self, val, expected):
        assert _to_float(val) == expected


class TestCollecteurImport:
    """Vérifie que tous les collecteurs s'importent sans erreur."""
    @pytest.mark.parametrize("module,cls", [
        ("core.collectors.leboncoin", "LeBonCoinCollector"),
        ("core.collectors.bienici",   "BienIciCollector"),
        ("core.collectors.seloger",   "SeLogerCollector"),
        ("core.collectors.pap",       "PAPCollector"),
        ("core.collectors.figaro",    "FigaroCollector"),
    ])
    def test_import(self, module, cls):
        import importlib
        mod = importlib.import_module(module)
        klass = getattr(mod, cls)
        instance = klass(RECHERCHE)
        assert hasattr(instance, "collecter")
        assert hasattr(instance, "source")
        assert instance.source != ""
