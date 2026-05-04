"""
Orchestrateur de collecte — lance tous les collecteurs actifs
pour toutes les recherches configurées.
"""

import logging
from concurrent.futures import ThreadPoolExecutor, as_completed

log = logging.getLogger("collectors")

_COLLECTOR_MAP = {
    "leboncoin": "core.collectors.leboncoin.LeBonCoinCollector",
    "bienici":   "core.collectors.bienici.BienIciCollector",
    "seloger":   "core.collectors.seloger.SeLogerCollector",
    "pap":       "core.collectors.pap.PAPCollector",
    "figaro":    "core.collectors.figaro.FigaroCollector",
}


def _load_class(dotpath: str):
    module_path, cls_name = dotpath.rsplit(".", 1)
    import importlib
    mod = importlib.import_module(module_path)
    return getattr(mod, cls_name)


def collecter_tout(settings) -> list:
    """
    Lance tous les collecteurs actifs pour toutes les recherches.
    Retourne la liste complète d'annonces normalisées.
    """
    toutes = []
    sources_actives = {k for k, v in settings.SOURCES.items() if v}
    recherches_actives = [r for r in settings.RECHERCHES if r.get("actif", True)]

    log.info(f"Sources actives : {sorted(sources_actives)}")
    log.info(f"Recherches actives : {[r['id'] for r in recherches_actives]}")

    tasks = []
    for recherche in recherches_actives:
        for source_name, dotpath in _COLLECTOR_MAP.items():
            if source_name not in sources_actives:
                continue
            tasks.append((source_name, dotpath, recherche))

    log.info(f"Total tâches de collecte : {len(tasks)}")

    # Parallélisme léger (2 workers max pour ne pas surcharger les sites)
    # LBC doit tourner en série (Datadome bloque les appels parallèles)
    # Autres sources : 2 workers en parallèle
    lbc_tasks    = [(s,d,r) for s,d,r in tasks if s == "leboncoin"]
    autres_tasks = [(s,d,r) for s,d,r in tasks if s != "leboncoin"]

    def run_tasks(task_list, workers=2):
        with ThreadPoolExecutor(max_workers=workers) as executor:
            futures = {
                executor.submit(_run_collector, dotpath, recherche): (source_name, recherche["id"])
                for source_name, dotpath, recherche in task_list
            }
            for future in as_completed(futures):
                source, rid = futures[future]
                try:
                    annonces = future.result()
                    toutes.extend(annonces)
                    log.info(f"  ✓ {source}/{rid} → {len(annonces)} annonces")
                except Exception as e:
                    log.error(f"  ✗ {source}/{rid} → erreur : {e}")

    # LBC en série (workers=1), autres en parallèle (workers=2)
    run_tasks(lbc_tasks, workers=1)
    run_tasks(autres_tasks, workers=2)
    log.info(f"Collecte terminée : {len(toutes)} annonces brutes")
    return toutes


def _run_collector(dotpath: str, recherche: dict) -> list:
    cls = _load_class(dotpath)
    collector = cls(recherche)
    return collector.collecter()
