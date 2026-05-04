"""
Dashboard Flask — visualisation des annonces scorées.
Lance avec : python dashboard/app.py
Accès : http://localhost:5000
"""

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from flask import Flask, jsonify, render_template, request

from config import settings
from core.database import ImmoDB

app = Flask(__name__)
db  = ImmoDB(settings.DB_PATH)


@app.route("/")
def index():
    return render_template("index.html")


@app.route("/carte")
def carte():
    return render_template("carte.html")


@app.route("/api/annonces")
def api_annonces():
    source   = request.args.get("source")
    min_score = int(request.args.get("min_score", 0))
    limite    = int(request.args.get("limite", 100))
    recherche = request.args.get("recherche")

    conn = db._conn()
    q = "SELECT * FROM annonces WHERE 1=1"
    params = []

    if source:
        q += " AND source=?"; params.append(source)
    if min_score:
        q += " AND score_final>=?"; params.append(min_score)
    if recherche:
        q += " AND recherche_id=?"; params.append(recherche)

    q += f" ORDER BY score_final DESC NULLS LAST, date_vue DESC LIMIT {limite}"

    import sqlite3
    conn.row_factory = sqlite3.Row
    rows = conn.execute(q, params).fetchall()

    def parse_row(r):
        d = dict(r)
        for field in ("points_forts", "points_vigilance", "questions"):
            try:
                d[field] = json.loads(d.get(field) or "[]")
            except Exception:
                d[field] = []
        return d

    return jsonify([parse_row(r) for r in rows])


@app.route("/api/stats")
def api_stats():
    return jsonify({
        "statuts":  db.stats(),
        "sources":  db.stats_sources(),
        "top_jour": len(db.top_du_jour(seuil=60)),
    })


@app.route("/api/annonce/<annonce_id>/statut", methods=["POST"])
def update_statut(annonce_id):
    data   = request.get_json()
    statut = data.get("statut", "")
    notes  = data.get("notes", "")
    valides = {"nouveau", "a_appeler", "a_visiter", "rejeté", "offre", "acquis"}
    if statut not in valides:
        return jsonify({"error": "statut invalide"}), 400
    db.marquer_statut(annonce_id, statut, notes)
    return jsonify({"ok": True})


if __name__ == "__main__":
    print("Dashboard : http://localhost:5000")
    app.run(debug=True, host="0.0.0.0", port=5000)
