"""
Enrichissement des annonces :
  - Géocodage via Nominatim (OpenStreetMap, gratuit, open source)
  - Calcul de distance aux campus (geopy)
  - Estimation loyer et rentabilité brute/nette
  - GéoRisques simplifié (API officielle georisques.gouv.fr)

Pas de clé API requise — tout open source.
"""

import logging
import math
import time

import requests

log = logging.getLogger("enricher")

# Loyers de référence par ville et type de bien (€/m², source indices INSEE/observatoires locaux)
_LOYERS_REF = {
    "Grenoble":         {"appartement": 13.5, "maison": 11.0, "studio": 14.5},
    "Lyon":             {"appartement": 16.0, "maison": 13.0, "studio": 17.5},
    "Clermont-Ferrand": {"appartement": 10.5, "maison": 9.0,  "studio": 11.5},
    "Allevard":         {"appartement": 9.0,  "maison": 8.5,  "studio": 10.0},
    "default":          {"appartement": 12.0, "maison": 10.0, "studio": 13.0},
}

# Campus universitaires Grenoble
_CAMPUS_GRE = [
    {"nom": "UGA Domaine Univ.", "lat": 45.1933, "lng": 5.7687},
    {"nom": "Grenoble INP",       "lat": 45.1956, "lng": 5.7698},
    {"nom": "Sciences Po Gren.",  "lat": 45.1880, "lng": 5.7262},
]
_CAMPUS_LYON = [
    {"nom": "Campus La Doua",   "lat": 45.7824, "lng": 4.8692},
    {"nom": "Lyon 2 Berges",    "lat": 45.7490, "lng": 4.8334},
    {"nom": "EM Lyon",          "lat": 45.7414, "lng": 4.8757},
]
_CAMPUS_CF = [
    {"nom": "Univ. Clermont",   "lat": 45.7764, "lng": 3.0870},
]
_CAMPUS_MAP = {
    "Grenoble":         _CAMPUS_GRE,
    "Lyon":             _CAMPUS_LYON,
    "Clermont-Ferrand": _CAMPUS_CF,
}

_NOMINATIM_URL = "https://nominatim.openstreetmap.org/search"
_GEORISQUES_URL = "https://georisques.gouv.fr/api/v1/gaspar/risques"

HEADERS = {"User-Agent": "immo-bot/1.0 (github.com/immo-bot; usage personnel)"}


# ── Géocodage ──────────────────────────────────────────────────────────────

def geocoder(adresse: str, ville: str) -> tuple[float, float] | tuple[None, None]:
    """Retourne (lat, lng) via Nominatim. Respecte le rate limit 1 req/s."""
    query = f"{adresse}, {ville}, France" if adresse else f"{ville}, France"
    try:
        resp = requests.get(
            _NOMINATIM_URL,
            params={"q": query, "format": "json", "limit": 1, "countrycodes": "fr"},
            headers=HEADERS,
            timeout=8,
        )
        time.sleep(1.1)  # Nominatim impose 1 req/s
        if resp.status_code == 200 and resp.json():
            r = resp.json()[0]
            return float(r["lat"]), float(r["lon"])
    except Exception as e:
        log.debug(f"Nominatim erreur pour '{query}' : {e}")
    return None, None


# ── Distance haversine ──────────────────────────────────────────────────────

def distance_km(lat1: float, lng1: float, lat2: float, lng2: float) -> float:
    """Distance haversine en km entre deux points GPS."""
    R = 6371.0
    d_lat = math.radians(lat2 - lat1)
    d_lng = math.radians(lng2 - lng1)
    a = math.sin(d_lat/2)**2 + math.cos(math.radians(lat1)) * math.cos(math.radians(lat2)) * math.sin(d_lng/2)**2
    return R * 2 * math.asin(math.sqrt(a))


# ── Campus ─────────────────────────────────────────────────────────────────

def campus_le_plus_proche(lat: float, lng: float, ville: str) -> tuple[float, str]:
    """Retourne (distance_km, nom_campus) pour la ville donnée."""
    campus_list = _CAMPUS_MAP.get(ville, _CAMPUS_GRE)
    best_dist = 999.0
    best_nom = ""
    for c in campus_list:
        d = distance_km(lat, lng, c["lat"], c["lng"])
        if d < best_dist:
            best_dist = d
            best_nom = c["nom"]
    return round(best_dist, 2), best_nom


# ── GéoRisques ─────────────────────────────────────────────────────────────

def risques_geo(lat: float, lng: float) -> str:
    """
    Interroge l'API georisques.gouv.fr pour les risques naturels.
    Retourne une string résumée (ex: "Inondation,Séisme") ou "RAS".
    """
    try:
        resp = requests.get(
            _GEORISQUES_URL,
            params={"latlon": f"{lng},{lat}", "rayon": 500},
            headers=HEADERS,
            timeout=8,
        )
        if resp.status_code == 200:
            data = resp.json()
            risques = []
            for r in data.get("risques", []):
                lib = r.get("libelle_risque_jo") or r.get("libelle_risque", "")
                if lib and lib not in risques:
                    risques.append(lib)
            return ", ".join(risques[:4]) if risques else "RAS"
    except Exception as e:
        log.debug(f"GéoRisques erreur : {e}")
    return ""


# ── Rentabilité ─────────────────────────────────────────────────────────────

def calculer_rentabilite(prix: int, surface: float, ville: str, type_bien: str) -> dict:
    """
    Calcule loyer estimé, rendement brut et rendement net simplifié.
    Basé sur les indices de loyer de référence locaux.
    """
    if not prix or not surface or surface <= 0 or prix <= 0:
        return {"loyer_estime": None, "rendement_brut": None, "rendement_net": None}

    ref = _LOYERS_REF.get(ville, _LOYERS_REF["default"])
    loyer_m2 = ref.get(type_bien or "appartement", ref["appartement"])
    loyer_mensuel = round(loyer_m2 * surface)

    # Rendement brut = (loyer annuel / prix) * 100
    rendement_brut = round((loyer_mensuel * 12 / prix) * 100, 2)

    # Rendement net simplifié (- 30% charges, fiscalité, vacance)
    rendement_net = round(rendement_brut * 0.70, 2)

    return {
        "loyer_estime":   loyer_mensuel,
        "rendement_brut": rendement_brut,
        "rendement_net":  rendement_net,
    }


# ── Enrichissement complet ──────────────────────────────────────────────────

def enrichir(annonce: dict) -> dict:
    """
    Enrichit une annonce avec les données géo et financières.
    Retourne un dict compatible avec db.mettre_a_jour_geo().
    """
    geo = {
        "dist_campus_km":  None,
        "campus_proche":   None,
        "dist_gare_km":    None,
        "risque_geo":      None,
        "loyer_estime":    None,
        "rendement_brut":  None,
        "rendement_net":   None,
    }

    lat = annonce.get("lat")
    lng = annonce.get("lng")
    ville = annonce.get("ville", "")

    # Géocodage si coordonnées manquantes
    if not lat or not lng:
        lat, lng = geocoder(annonce.get("adresse"), ville)

    if lat and lng:
        # Distance campus
        dist, campus = campus_le_plus_proche(float(lat), float(lng), ville)
        geo["dist_campus_km"] = dist
        geo["campus_proche"]  = campus

        # GéoRisques (surtout utile pour zone alpine)
        geo["risque_geo"] = risques_geo(float(lat), float(lng))

    # Rentabilité
    rent = calculer_rentabilite(
        prix=annonce.get("prix"),
        surface=annonce.get("surface"),
        ville=ville,
        type_bien=annonce.get("type_bien"),
    )
    geo.update(rent)

    return geo
