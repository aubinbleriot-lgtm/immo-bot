"""Classe de base pour tous les collecteurs d'annonces."""

import hashlib
import logging
import random
import time
from abc import ABC, abstractmethod

log = logging.getLogger(__name__)

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/124.0.0.0 Safari/537.36"
    ),
    "Accept-Language": "fr-FR,fr;q=0.9,en;q=0.8",
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
}


def delai_humain(min_s=2.0, max_s=5.0):
    time.sleep(random.uniform(min_s, max_s))


def annonce_hash(source: str, url: str) -> str:
    """ID unique par annonce (source + URL)."""
    return hashlib.sha256(f"{source}|{url}".encode()).hexdigest()[:20]


def empreinte_bien(ville: str, surface, prix, nb_pieces=None) -> str | None:
    """
    Empreinte physique du bien, INDÉPENDANTE de la source.

    Permet de détecter qu'un même logement est publié sur LBC, Bien'ici
    et PAP simultanément, ou réapparaît le lendemain avec un ID différent.

    Tolérances :
      - surface  : arrondie à 5 m²  (ex: 22 m² ≡ 22.3 m²)
      - prix     : arrondi à 5 000€ (ex: 85 000 ≡ 84 900)
      - pièces   : exact (un T1 ≠ T2)
      - ville    : normalisée minuscule sans accents

    Retourne None si données insuffisantes (pas de surface ou prix).
    """
    if not ville or not surface or not prix:
        return None
    try:
        surf_norm  = round(float(surface) / 5) * 5
        prix_norm  = round(float(prix) / 5000) * 5000
        ville_norm = (ville.lower().strip()
                      .replace("é","e").replace("è","e").replace("ê","e")
                      .replace("à","a").replace("â","a"))
        pieces     = int(nb_pieces) if nb_pieces else 0
        s = f"{ville_norm}|{surf_norm}|{prix_norm}|{pieces}"
        return hashlib.sha256(s.encode()).hexdigest()[:16]
    except Exception:
        return None


def normaliser_annonce(raw: dict, source: str, recherche: dict) -> dict:
    """Convertit une annonce brute en format commun, avec empreinte cross-source."""
    url = raw.get("url", "")
    ville = raw.get("ville") or recherche.get("ville")
    prix = _to_int(raw.get("prix"))
    surface = _to_float(raw.get("surface"))
    nb_pieces = _to_int(raw.get("nb_pieces"))

    return {
        "id":           annonce_hash(source, url),
        "empreinte":    empreinte_bien(ville, surface, prix, nb_pieces),
        "source":       source,
        "recherche_id": recherche["id"],
        "type_bien":    raw.get("type_bien"),
        "titre":        raw.get("titre", "")[:500],
        "prix":         prix,
        "surface":      surface,
        "ville":        ville,
        "code_postal":  raw.get("code_postal"),
        "adresse":      raw.get("adresse"),
        "lat":          _to_float(raw.get("lat")),
        "lng":          _to_float(raw.get("lng")),
        "url":          url,
        "description":  raw.get("description", "")[:5000],
        "nb_pieces":    nb_pieces,
        "nb_chambres":  _to_int(raw.get("nb_chambres")),
        "dpe":          raw.get("dpe"),
        "ges":          raw.get("ges"),
        "charges":      _to_int(raw.get("charges")),
        "date_publiee": raw.get("date_publiee"),
    }


def _to_int(v):
    try:
        return int(float(str(v).replace(" ", "").replace("\u202f", "").replace(",", "."))) if v else None
    except Exception:
        return None


def _to_float(v):
    try:
        return float(str(v).replace(",", ".")) if v else None
    except Exception:
        return None


class BaseCollector(ABC):
    source: str = ""

    def __init__(self, recherche: dict):
        self.recherche = recherche
        self.log = logging.getLogger(f"collector.{self.source}")

    @abstractmethod
    def collecter(self) -> list:
        ...

    def _norm(self, raw: dict) -> dict:
        return normaliser_annonce(raw, self.source, self.recherche)
