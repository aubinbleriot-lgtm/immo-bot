"""
Collecteur Bien'ici — endpoint JSON natif.

Correctif filtre propertyType : l'API BienIci nécessite le paramètre
'filterType' en plus de 'propertyType' pour filtrer efficacement.
On ajoute aussi une validation post-collecte pour rejeter les biens
commerciaux ou hors zone qui passeraient quand même.
"""

import json
import logging
import requests
from core.collectors.base import BaseCollector, HEADERS, delai_humain

log = logging.getLogger("collector.bienici")
API_URL = "https://www.bienici.com/realEstateAds.json"

_TYPE_MAP = {
    "appartement": ["appartement"],
    "maison":      ["maison"],
    "studio":      ["appartement"],
    "terrain":     ["terrain"],
    "parking":     ["parking"],
}

# Types commerciaux à rejeter explicitement
_TYPES_COMMERCIAUX = {
    "bureau", "local", "entrepôt", "commerce", "local commercial",
    "local d'activité", "fonds de commerce", "murs commerciaux",
    "cellule", "hangar", "terrain commercial",
}


def _est_commercial(ad: dict) -> bool:
    """Rejette les biens commerciaux qui passent malgré le filtre."""
    pt = (ad.get("propertyType") or "").lower()
    titre = (ad.get("title") or "").lower()
    if pt in _TYPES_COMMERCIAUX:
        return True
    mots = ["entrepôt", "local d'activité", "local commercial", "cellule d'activité",
            "fonds de commerce", "bureau à louer", "logistique"]
    return any(m in titre for m in mots)


class BienIciCollector(BaseCollector):
    source = "bienici"

    def collecter(self) -> list:
        r = self.recherche
        annonces = []
        types = []
        for t in r.get("types_bien", ["appartement"]):
            types.extend(_TYPE_MAP.get(t.lower(), ["appartement"]))

        filters = {
            "size": min(r.get("max_par_source", 40), 40),
            "from": 0,
            "filters": {
                "status":             "active",
                "adTypePricingEnum":  "sales",   # vente uniquement
                "filterType":         "buy",      # doublon explicite pour forcer la vente
                "propertyType":       types,
                "priceMin":  r.get("prix_min", 0),
                "priceMax":  r.get("prix_max", 9_000_000),
                "surfaceMin": r.get("surface_min", 1),
                "surfaceMax": r.get("surface_max", 9_999),
                "circle": {
                    "lat":    r["lat"],
                    "lng":    r["lng"],
                    "radius": r["rayon_km"] * 1000,
                },
            },
            "sortBy":               "publicationDate",
            "sortOrder":            "desc",
            "onlyFetchAggregates":  False,
            "lang":                 "fr",
        }

        try:
            session = requests.Session()
            session.headers.update(HEADERS)
            session.headers.update({
                "Accept":           "application/json, text/plain, */*",
                "x-requested-with": "XMLHttpRequest",
                "Referer":          "https://www.bienici.com/recherche/achat/france",
            })

            resp = session.get(
                API_URL,
                params={"filters": json.dumps(filters, ensure_ascii=False)},
                timeout=20,
            )

            if resp.status_code == 403:
                log.warning(f"BienIci [{r['id']}] bloqué 403")
                return []
            if resp.status_code != 200:
                log.warning(f"BienIci [{r['id']}] HTTP {resp.status_code}")
                return []

            ads = resp.json().get("realEstateAds", [])
            rejets = 0

            for ad in ads:
                # Filtrage post-collecte : rejeter les biens commerciaux
                if _est_commercial(ad):
                    rejets += 1
                    continue

                ad_id = ad.get("id", "")
                url   = ad.get("url") or _build_url(ad, ad_id)
                raw = {
                    "titre":        _titre(ad),
                    "prix":         ad.get("price"),
                    "surface":      ad.get("surfaceArea"),
                    "ville":        ad.get("city"),
                    "code_postal":  ad.get("postalCode"),
                    "adresse":      ad.get("address"),
                    "lat":          _coord(ad, "lat"),
                    "lng":          _coord(ad, "lon") or _coord(ad, "lng"),
                    "url":          url,
                    "description":  ad.get("description", ""),
                    "nb_pieces":    ad.get("roomsQuantity"),
                    "nb_chambres":  ad.get("bedroomsQuantity"),
                    "type_bien":    ad.get("propertyType", r.get("types_bien", [""])[0]),
                    "dpe":          ad.get("energyClassification"),
                    "ges":          ad.get("greenhouseGazClassification"),
                    "charges":      ad.get("monthlyCharges"),
                    "date_publiee": ad.get("publicationDate"),
                }
                if raw["url"] and raw["titre"]:
                    annonces.append(self._norm(raw))

            if rejets:
                log.info(f"BienIci [{r['id']}] → {len(annonces)} annonces ({rejets} commerciaux rejetés)")
            else:
                log.info(f"BienIci [{r['id']}] → {len(annonces)} annonces")

            delai_humain(2, 5)

        except Exception as e:
            log.error(f"BienIci erreur [{r['id']}] : {e}")

        return annonces


def _titre(ad: dict) -> str:
    if ad.get("title"):
        return ad["title"]
    parts = [ad.get("propertyType", "bien")]
    if ad.get("surfaceArea"): parts.append(f"{ad['surfaceArea']}m²")
    if ad.get("city"):        parts.append(ad["city"])
    if ad.get("price"):       parts.append(f"{ad['price']}€")
    return " — ".join(parts)

def _coord(ad: dict, key: str) -> float | None:
    v = ad.get("blurInfo", {}).get("position", {}).get(key)
    return v if v is not None else ad.get(key)

def _build_url(ad: dict, ref: str) -> str:
    if not ref: return ""
    city  = (ad.get("city") or "france").lower().replace(" ", "-")
    cp    = ad.get("postalCode", "")
    pt    = (ad.get("propertyType") or "bien").lower()
    rooms = ad.get("roomsQuantity")
    slug  = f"{city}-{cp}" if cp else city
    nb    = f"{rooms}pieces" if rooms else "bien"
    return f"https://www.bienici.com/annonce/vente/{slug}/{pt}/{nb}/{ref}"
