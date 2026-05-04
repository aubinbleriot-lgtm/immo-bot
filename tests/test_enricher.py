"""Tests unitaires — enrichissement géo et calcul de rentabilité."""

import pytest
from unittest.mock import patch, MagicMock
from core.enricher import (
    calculer_rentabilite, campus_le_plus_proche,
    distance_km, enrichir,
)


class TestDistanceKm:
    def test_meme_point(self):
        assert distance_km(45.19, 5.74, 45.19, 5.74) == pytest.approx(0.0, abs=0.001)

    def test_grenoble_lyon(self):
        """Grenoble → Lyon ≈ 100 km."""
        d = distance_km(45.1875, 5.7358, 45.7640, 4.8357)
        assert 95 <= d <= 110

    def test_uga_sciences_po(self):
        """UGA Domaine Univ → Sciences Po Grenoble ≈ 4 km."""
        d = distance_km(45.1933, 5.7687, 45.1880, 5.7262)
        assert 2.5 <= d <= 5.5


class TestCampusPlusProche:
    def test_proche_uga(self):
        """Coordonnées proches de l'UGA → campus UGA retourné."""
        dist, nom = campus_le_plus_proche(45.192, 5.770, "Grenoble")
        assert dist < 2.0
        assert "UGA" in nom or "Grenoble" in nom

    def test_loin_campus(self):
        """Coordonnées éloignées → distance > 10 km."""
        dist, nom = campus_le_plus_proche(44.0, 5.0, "Grenoble")
        assert dist > 10.0

    def test_ville_inconnue(self):
        """Ville non mappée → fallback sans crash."""
        dist, nom = campus_le_plus_proche(45.0, 5.0, "VilleInconnue")
        assert isinstance(dist, float)
        assert isinstance(nom, str)


class TestCalculerRentabilite:
    def test_cas_normal_grenoble(self):
        r = calculer_rentabilite(90_000, 22, "Grenoble", "appartement")
        assert r["loyer_estime"] > 0
        assert 0 < r["rendement_brut"] < 20
        assert r["rendement_net"] < r["rendement_brut"]
        assert r["rendement_net"] == pytest.approx(r["rendement_brut"] * 0.70, rel=0.01)

    def test_prix_nul(self):
        r = calculer_rentabilite(0, 22, "Grenoble", "appartement")
        assert r["loyer_estime"] is None
        assert r["rendement_brut"] is None

    def test_surface_nulle(self):
        r = calculer_rentabilite(90_000, 0, "Grenoble", "appartement")
        assert r["rendement_brut"] is None

    def test_ville_inconnue(self):
        """Doit utiliser 'default' sans crash."""
        r = calculer_rentabilite(100_000, 30, "VilleInconnue", "appartement")
        assert r["loyer_estime"] > 0

    @pytest.mark.parametrize("type_bien", ["appartement", "maison", "studio"])
    def test_tous_types_biens(self, type_bien):
        r = calculer_rentabilite(100_000, 30, "Grenoble", type_bien)
        assert r["loyer_estime"] > 0

    def test_rendement_coherent(self):
        """Studio 22m² à 85k à Grenoble → rendement raisonnable (2-8%)."""
        r = calculer_rentabilite(85_000, 22, "Grenoble", "studio")
        assert 2.0 <= r["rendement_brut"] <= 10.0

    def test_loyer_grenoble_superieur_clermont(self):
        """Grenoble a des loyers plus élevés que Clermont-Ferrand."""
        r_gre = calculer_rentabilite(100_000, 30, "Grenoble", "appartement")
        r_clf = calculer_rentabilite(100_000, 30, "Clermont-Ferrand", "appartement")
        assert r_gre["loyer_estime"] > r_clf["loyer_estime"]


class TestEnrichirComplet:
    def test_avec_coordonnees(self):
        """Si lat/lng présentes → pas d'appel Nominatim."""
        annonce = {
            "id": "t1", "lat": 45.185, "lng": 5.736,
            "ville": "Grenoble", "type_bien": "appartement",
            "prix": 90_000, "surface": 22,
            "adresse": "1 rue de la Paix",
        }
        with patch("core.enricher.risques_geo", return_value="RAS"):
            geo = enrichir(annonce)

        assert geo["dist_campus_km"] is not None
        assert geo["dist_campus_km"] < 10.0
        assert geo["campus_proche"] is not None
        assert geo["loyer_estime"] is not None
        assert geo["rendement_brut"] is not None

    def test_sans_coordonnees_geocodage(self):
        """Si pas de lat/lng → Nominatim appelé."""
        annonce = {
            "id": "t2", "lat": None, "lng": None,
            "ville": "Grenoble", "type_bien": "appartement",
            "prix": 90_000, "surface": 22,
            "adresse": "Place Grenette",
        }
        with patch("core.enricher.geocoder", return_value=(45.191, 5.724)) as mock_geo, \
             patch("core.enricher.risques_geo", return_value="RAS"):
            geo = enrichir(annonce)
            mock_geo.assert_called_once()

        assert geo["dist_campus_km"] is not None

    def test_sans_prix_pas_crash(self):
        """Annonce sans prix → rentabilité None, pas de crash."""
        annonce = {
            "id": "t3", "lat": 45.185, "lng": 5.736,
            "ville": "Grenoble", "type_bien": "appartement",
            "prix": None, "surface": None,
        }
        with patch("core.enricher.risques_geo", return_value=""):
            geo = enrichir(annonce)

        assert geo["loyer_estime"] is None
        assert geo["rendement_brut"] is None
