"""
Scoring hybride : calculs déterministes (pondérations du document) + Gemini (texte).

Le document original définit des poids précis. On les applique objectivement
pour les critères quantifiables, et on délègue à Gemini uniquement l'analyse
du texte (signaux positifs/vigilance) qui ne peut pas être calculée.

Plan B locatif /100 :
  Rentabilité brute      20 pts
  Prix vs marché         15 pts
  Proximité campus       15 pts
  Proximité transports   10 pts (approché via dist_campus)
  Tension locative       10 pts (approché via ville)
  Qualité bien            10 pts (Gemini texte)
  DPE                    10 pts
  Charges faibles         5 pts
  Potentiel amélioration  5 pts (Gemini texte)

Plan A résidence /100 :
  Cadre/calme            15 pts (Gemini)
  Terrain                15 pts (Gemini)
  Temps Grenoble         15 pts (dist_campus ≈ approché)
  Prix vs marché         15 pts
  État général           10 pts (Gemini)
  Écoles/services        10 pts (Gemini)
  Risques naturels       10 pts (risque_geo)
  DPE                     5 pts
  Potentiel patrimoine    5 pts (Gemini)
"""

import json
import logging
import re
import time

from core.llm import appel_llm

log = logging.getLogger("scorer")

# ── Tables de scoring déterministe ─────────────────────────────────────────

def _score_dpe(dpe: str | None) -> int:
    table = {"A": 10, "B": 9, "C": 7, "D": 5, "E": 3, "F": 1, "G": 0}
    return table.get((dpe or "").upper().strip(), 4)


def _score_rendement(rendement_brut: float | None) -> int:
    if rendement_brut is None: return 0
    if rendement_brut >= 8:    return 20
    if rendement_brut >= 6:    return 15
    if rendement_brut >= 4.5:  return 10
    if rendement_brut >= 3:    return 5
    return 0


def _score_prix_marche(prix: int | None, prix_m2: float | None, ville: str, type_bien: str) -> int:
    """Compare le prix/m² à la médiane locale estimée."""
    _MEDIANE = {
        "Grenoble": {"appartement": 3200, "studio": 3400, "maison": 2800},
        "Lyon":     {"appartement": 4500, "studio": 4800, "maison": 3800},
        "Clermont-Ferrand": {"appartement": 2000, "studio": 2200, "maison": 1800},
        "default":  {"appartement": 2500, "studio": 2700, "maison": 2200},
    }
    if not prix_m2: return 5  # neutre si inconnu
    ref = _MEDIANE.get(ville, _MEDIANE["default"])
    mediane = ref.get(type_bien or "appartement", 2500)
    ratio = prix_m2 / mediane
    if ratio < 0.80:  return 15  # >20% sous le marché
    if ratio < 0.90:  return 12
    if ratio < 1.00:  return 9
    if ratio < 1.10:  return 6
    if ratio < 1.20:  return 3
    return 0


def _score_campus(dist_km: float | None) -> int:
    if dist_km is None: return 5  # neutre
    if dist_km <= 0.5:  return 15
    if dist_km <= 1.0:  return 12
    if dist_km <= 2.0:  return 9
    if dist_km <= 3.5:  return 6
    if dist_km <= 6.0:  return 3
    return 0


def _score_risques(risque_geo: str | None) -> int:
    if not risque_geo or risque_geo == "RAS":
        return 10
    risque_lower = risque_geo.lower()
    if any(x in risque_lower for x in ["inondation", "avalanche", "glissement"]):
        return 2
    if "séisme" in risque_lower or "sismique" in risque_lower:
        return 5
    return 7


def _score_tension_locative(ville: str) -> int:
    """Score de tension locative par ville (source : observatoires des loyers)."""
    haute    = {"Grenoble", "Lyon", "Paris", "Bordeaux", "Toulouse"}
    moyenne  = {"Clermont-Ferrand", "Nantes", "Rennes", "Strasbourg"}
    if ville in haute:   return 10
    if ville in moyenne: return 6
    return 3


# ── Scoring déterministe ───────────────────────────────────────────────────

def score_plan_b(annonce: dict) -> int:
    """Plan B — locatif étudiant /100 (critères déterministes = 70 pts max)."""
    score = 0
    score += _score_rendement(annonce.get("rendement_brut"))          # 20
    score += _score_prix_marche(
        annonce.get("prix"), annonce.get("prix_m2"),
        annonce.get("ville", ""), annonce.get("type_bien", "appartement"))  # 15
    score += _score_campus(annonce.get("dist_campus_km"))              # 15
    score += min(10, _score_campus(annonce.get("dist_campus_km")) // 2 + 5)  # transports approché: 10
    score += _score_tension_locative(annonce.get("ville", ""))         # 10
    score += _score_dpe(annonce.get("dpe"))                            # 10
    # 10 pts restants = Gemini (qualité bien + potentiel)
    return min(score, 90)  # plafond avant bonus Gemini


def score_plan_a(annonce: dict) -> int:
    """Plan A — résidence principale /100 (critères déterministes = 30 pts max)."""
    score = 0
    score += _score_prix_marche(
        annonce.get("prix"), annonce.get("prix_m2"),
        annonce.get("ville", ""), annonce.get("type_bien", "maison"))   # 15
    score += _score_risques(annonce.get("risque_geo"))                  # 10
    score += _score_dpe(annonce.get("dpe"))                             # 5
    # 70 pts restants = Gemini (cadre, terrain, état, services...)
    return min(score, 30)


# ── LLM — analyse texte (multi-provider) ────────────────────────────────────


_SYSTEM = """Tu es un expert en investissement immobilier français.
Tu évalues des annonces pour deux profils :
  Plan A : résidence principale, maison, Isère/Grenoble, jardin, calme, famille.
  Plan B : locatif étudiant, studio/T2, proche campus, rendement.
Réponds UNIQUEMENT en JSON valide, sans markdown."""

_PROMPT = """Annonce :
Source: {source} | Recherche: {recherche_id}
Titre: {titre}
Prix: {prix}€ | Surface: {surface}m² | Prix/m²: {prix_m2}€/m²
Ville: {ville} | DPE: {dpe} | Pièces: {nb_pieces}
Campus proche: {campus} ({dist_campus}km)
Rendement brut estimé: {rendement}%
Risques naturels: {risques}
Description: {description}

Retourne ce JSON :
{{
  "bonus_a": <entier 0-70, bonus qualitatif Plan A>,
  "bonus_b": <entier 0-10, bonus qualitatif Plan B>,
  "verdict": "<PÉPITE|TRÈS INTÉRESSANT|À SURVEILLER|MOYEN|À ÉVITER>",
  "points_forts": ["<max 3 points>"],
  "points_vigilance": ["<max 3 vigilances>"],
  "questions": ["<2 questions à poser au vendeur>"],
  "resume_ia": "<2 phrases max>"
}}"""


def scorer_annonce(settings, annonce: dict) -> dict:
    """
    Scoring hybride complet :
    1. Calcul déterministe (pondérations du document)
    2. Bonus qualitatif LLM (multi-provider : Groq → OpenRouter → Gemini)
    3. Score final = déterministe + bonus LLM
    """
    recherche_id = annonce.get("recherche_id", "")
    est_locatif  = "locatif" in recherche_id or annonce.get("type_bien") in ("appartement", "studio")

    # Scores déterministes
    score_a_base = score_plan_a(annonce)
    score_b_base = score_plan_b(annonce)

    # Analyse LLM (bonus qualitatif) — multi-provider avec fallback
    has_llm = any([
        getattr(settings, "GROQ_API_KEY", ""),
        getattr(settings, "OPENROUTER_API_KEY", ""),
        getattr(settings, "GEMINI_API_KEY", ""),
    ])
    gemini_result = _appel_llm(settings, annonce) if has_llm else _gemini_vide()

    # Score final Plan A = base (30) + bonus_a Gemini (0-70)
    score_a = min(score_a_base + gemini_result.get("bonus_a", 0), 100)
    # Score final Plan B = base (90) + bonus_b Gemini (0-10)
    score_b = min(score_b_base + gemini_result.get("bonus_b", 0), 100)

    score_final = score_b if est_locatif else score_a

    return {
        "score_a":           score_a,
        "score_b":           score_b,
        "score_final":       score_final,
        "verdict":           gemini_result.get("verdict", _verdict_auto(score_final)),
        "points_forts":      gemini_result.get("points_forts", []),
        "points_vigilance":  gemini_result.get("points_vigilance", []),
        "questions":         gemini_result.get("questions", []),
        "resume_ia":         gemini_result.get("resume_ia", ""),
    }


def _appel_llm(settings, annonce: dict) -> dict:
    prix_m2 = annonce.get("prix_m2")
    if not prix_m2 and annonce.get("prix") and annonce.get("surface"):
        prix_m2 = round(annonce["prix"] / annonce["surface"])

    prompt = _PROMPT.format(
        source=annonce.get("source", ""),
        recherche_id=annonce.get("recherche_id", ""),
        titre=(annonce.get("titre") or "")[:200],
        prix=annonce.get("prix", "N/A"),
        surface=annonce.get("surface", "N/A"),
        prix_m2=prix_m2 or "N/A",
        ville=annonce.get("ville", "N/A"),
        dpe=annonce.get("dpe", "N/A"),
        nb_pieces=annonce.get("nb_pieces", "N/A"),
        campus=annonce.get("campus_proche", "N/A"),
        dist_campus=annonce.get("dist_campus_km", "N/A"),
        rendement=annonce.get("rendement_brut", "N/A"),
        risques=annonce.get("risque_geo", "N/A"),
        description=(annonce.get("description") or "")[:600],
    )
    return _with_retry(lambda: _call_llm(settings, prompt))


def _call_llm(settings, prompt: str) -> dict:
    text = appel_llm(settings, _SYSTEM, prompt)
    text = re.sub(r"```json\s*|```\s*", "", text)
    return json.loads(text)


def _with_retry(fn, retries: int = 3) -> dict:
    for attempt in range(retries):
        try:
            return fn()
        except Exception as e:
            if attempt == retries - 1:
                log.error(f"Gemini échec après {retries} tentatives : {e}")
                return _gemini_vide()
            m = re.search(r"retryDelay.*?(\d+)s", str(e))
            wait = int(m.group(1)) + 2 if m else min(2 ** (attempt + 2), 30)
            log.warning(f"Gemini retry dans {wait}s : {e}")
            time.sleep(wait)
    return _gemini_vide()


def _gemini_vide() -> dict:
    return {"bonus_a": 20, "bonus_b": 5, "verdict": "À SURVEILLER",
            "points_forts": [], "points_vigilance": [], "questions": [], "resume_ia": ""}


def _verdict_auto(score: int) -> str:
    if score >= 85: return "PÉPITE"
    if score >= 70: return "TRÈS INTÉRESSANT"
    if score >= 55: return "À SURVEILLER"
    if score >= 40: return "MOYEN"
    return "À ÉVITER"
