"""
Collecteur Bien'ici — endpoint JSON natif GET /realEstateAds.json.

Format correct (source : lobstr.io + inspection réseau) :
  GET https://www.bienici.com/realEstateAds.json?filters=<JSON_string>
  Le param 'filters' doit être json.dumps(), PAS str(dict).replace("'",'"').

URL annonce : BienIci retourne un champ 'id' = référence agence.
  On reconstruit depuis city + propertyType + rooms + id.
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
                "status": "active",
                "adTypePricingEnum": "sales",
                "propertyType": types,
                "priceMin": r.get("prix_min", 0),
                "priceMax": r.get("prix_max", 9_000_000),
                "surfaceMin": r.get("surface_min", 1),
                "surfaceMax": r.get("surface_max", 9_999),
                "circle": {"lat": r["lat"], "lng": r["lng"], "radius": r["rayon_km"] * 1000},
            },
            "sortBy": "publicationDate",
            "sortOrder": "desc",
            "onlyFetchAggregates": False,
            "lang": "fr",
        }

        try:
            session = requests.Session()
            session.headers.update(HEADERS)
            session.headers.update({
                "Accept": "application/json, text/plain, */*",
                "x-requested-with": "XMLHttpRequest",
                "Referer": "https://www.bienici.com/recherche/achat/france",
            })

            # CORRECTION CRITIQUE : json.dumps() pas str(dict).replace("'",'"')
            resp = session.get(
                API_URL,
                params={"filters": json.dumps(filters, ensure_ascii=False)},
                timeout=20,
            )

            if resp.status_code == 403:
                log.warning(f"BienIci [{r['id']}] bloqué 403 — Cloudflare actif sur cette IP")
                return []
            if resp.status_code != 200:
                log.warning(f"BienIci [{r['id']}] HTTP {resp.status_code}")
                return []

            data = resp.json()
            ads = data.get("realEstateAds", [])

            for ad in ads:
                ad_id  = ad.get("id", "")
                url    = ad.get("url") or _build_url(ad, ad_id)
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

            log.info(f"BienIci [{r['id']}] → {len(annonces)} annonces")
            delai_humain(2, 5)

        except Exception as e:
            log.error(f"BienIci erreur [{r['id']}] : {e}")

        return annonces


def _titre(ad: dict) -> str:
    if ad.get("title"):
        return ad["title"]
    parts = [ad.get("propertyType","bien")]
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
