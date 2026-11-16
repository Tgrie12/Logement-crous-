#!/usr/bin/env python3
"""Surveille trouverunlogement.lescrous.fr (zone de Caen) et envoie un mail
pour chaque NOUVEAU logement disponible."""
import json, os, smtplib, ssl, sys, time
import urllib.request
from email.message import EmailMessage
from pathlib import Path

BASE = "https://trouverunlogement.lescrous.fr"
STATE = Path("logements_vus.json")

# Zone de Caen + Hérouville-Saint-Clair, Mondeville, Colombelles, Ifs, Fleury-sur-Orne
# (coin haut-gauche, coin bas-droit)
CAEN_BOX = [{"lon": -0.47, "lat": 49.24}, {"lon": -0.25, "lat": 49.12}]

SEARCH_ID = os.environ.get("SEARCH_ID", "").strip()
SMTP_HOST = os.environ.get("SMTP_HOST", "smtp.gmail.com")
SMTP_PORT = int(os.environ.get("SMTP_PORT", "465"))
SMTP_USER = os.environ.get("SMTP_USER", "")
SMTP_PASS = os.environ.get("SMTP_PASS", "")
MAIL_TO = os.environ.get("MAIL_TO", SMTP_USER)
HEADERS = {"User-Agent": "Mozilla/5.0 (crous-watch)", "Accept": "application/json",
           "Content-Type": "application/json"}


def http(path, payload=None):
    data = json.dumps(payload).encode() if payload is not None else None
    req = urllib.request.Request(BASE + path, data=data, headers=HEADERS,
                                 method="POST" if payload is not None else "GET")
    with urllib.request.urlopen(req, timeout=30) as r:
        return json.load(r)


def get_mechanism(tool_id):
    """Lit le type de phase (ex. 'flow', 'residual') dans la liste des phases."""
    try:
        for t in http("/api/fr/tools"):
            if str(t.get("id")) == str(tool_id):
                return t.get("mechanism", "flow")
    except Exception:
        pass
    return "flow"


def search_all(tool_id):
    mechanism = get_mechanism(tool_id)
    items, page = [], 1
    while True:
        body = {
            "idTool": int(tool_id), "need_aggregation": True,
            "page": page, "pageSize": 24, "sector": None,
            "occupationModes": [], "location": CAEN_BOX, "residence": None,
            "precision": 5, "equipment": [],
            "price": {"min": 0, "max": 10000000},
            "area": {"min": 0, "max": 400}, "toolMechanism": mechanism,
        }
        res = http(f"/api/fr/search/{tool_id}", body).get("results", {})
        batch = res.get("items", [])
        items += batch
        if len(items) >= res.get("total", {}).get("value", len(items)) or not batch:
            return items
        page += 1
        time.sleep(1)


def describe(it):
    res = it.get("residence") or {}
    rent = ((it.get("occupationModes") or [{}])[0].get("rent") or {})
    price = rent.get("min")
    return {
        "id": it.get("id"),
        "titre": it.get("label", "Logement"),
        "residence": res.get("label", ""),
        "adresse": res.get("address", ""),
        "surface": (it.get("area") or {}).get("min"),
        "loyer": f"{price/100:.2f} €" if isinstance(price, (int, float)) else "n.c.",
        "url": f"{BASE}/tools/{SEARCH_ID}/accommodations/{it.get('id')}",
    }


def send_mail(subject, body):
    msg = EmailMessage()
    msg["Subject"], msg["From"], msg["To"] = subject, SMTP_USER, MAIL_TO
    msg.set_content(body)
    with smtplib.SMTP_SSL(SMTP_HOST, SMTP_PORT, context=ssl.create_default_context()) as s:
        s.login(SMTP_USER, SMTP_PASS)
        s.send_message(msg)


def main():
    if "--tools" in sys.argv:  # affiche les phases pour trouver le bon SEARCH_ID
        print(json.dumps(http("/api/fr/tools"), indent=2, ensure_ascii=False))
        return
    if not SEARCH_ID:
        sys.exit("SEARCH_ID manquant. Lance `python crous_watch.py --tools` pour le trouver.")

    first_run = not STATE.exists()
    seen = set(json.loads(STATE.read_text())) if not first_run else set()
    current = [describe(i) for i in search_all(SEARCH_ID)]
    new = [l for l in current if str(l["id"]) not in seen]

    if first_run:
        send_mail("CROUS Caen : surveillance activée",
                  f"Surveillance démarrée. {len(current)} logement(s) actuellement listé(s), "
                  "tu seras prévenu pour chaque nouveau.")
    else:
        for l in new:
            send_mail(f"🏠 CROUS Caen : {l['titre']} – {l['loyer']}",
                      f"{l['titre']}\nRésidence : {l['residence']}\nAdresse : {l['adresse']}\n"
                      f"Surface : {l['surface']} m²\nLoyer : {l['loyer']}\n\nVoir/réserver : {l['url']}")
    STATE.write_text(json.dumps(sorted({str(l['id']) for l in current} | seen)))
    print(f"{len(current)} logements, {len(new)} nouveaux")


if __name__ == "__main__":
    main()
