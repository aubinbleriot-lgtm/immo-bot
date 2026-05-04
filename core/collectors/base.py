"""Classe de base pour tous les collecteurs d'annonces."""

import logging
import time
import random
from abc import ABC, abstractmethod

from core.database import annonce_hash

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
    """Délai aléatoire entre deux requêtes pour éviter la détection."""
    time.sleep(random.uniform(min_s, max_s))


def normaliser_annonce(raw: dict, source: str, recherche: dict) -> dict:
    """
    Convertit une annonce brute en format commun.
    Calcule l'id unique par hash url+source.
    """
    url = raw.get("url", "")
    return {
        "id":           annonce_hash(source, url),
        "source":       source,
        "recherche_id": recherche["id"],
        "type_bien":    raw.get("type_bien"),
        "titre":        raw.get("titre", "")[:500],
        "prix":         _to_int(raw.get("prix")),
        "surface":      _to_float(raw.get("surface")),
        "ville":        raw.get("ville", recherche.get("ville")),
        "code_postal":  raw.get("code_postal"),
        "adresse":      raw.get("adresse"),
        "lat":          _to_float(raw.get("lat")),
        "lng":          _to_float(raw.get("lng")),
        "url":          url,
        "description":  raw.get("description", "")[:5000],
        "nb_pieces":    _to_int(raw.get("nb_pieces")),
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
        """Retourne une liste de dicts normalisés."""
        ...

    def _norm(self, raw: dict) -> dict:
        return normaliser_annonce(raw, self.source, self.recherche)
