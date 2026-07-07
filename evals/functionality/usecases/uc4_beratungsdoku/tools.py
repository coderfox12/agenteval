"""
UC4 – Beratungsdokumentations-Agent (§61 VVG)

Deterministische Mock-Tools für die Erstellung von Beratungsprotokollen.
Simulieren Entitäts-Extraktion aus Gesprächsprotokollen, Pflichtfeld-Prüfung,
Protokoll-Generierung und Meldung fehlender Informationen.

§61 VVG Pflichtfelder für Beratungsprotokoll:
  Kundenwunsch, Bedarfsanalyse, Empfehlung, Begründung, Risikohinweise,
  Produktbezeichnung, Prämie, Laufzeit, Unterschrift/Datum
"""

from langchain_core.tools import tool


# ─── Pflichtfeld-Definition §61 VVG ──────────────────────────────────────────

VVG_REQUIRED_FIELDS = [
    "kundenwunsch",
    "bedarfsanalyse",
    "empfehlung",
    "begruendung",
    "risikohinweise",
    "produktbezeichnung",
    "praemie_eur",
    "laufzeit_jahre",
    "beratungsdatum",
]

# ─── Mock-Transkript-Datenbank ────────────────────────────────────────────────

TRANSCRIPT_DB = {
    "TRANS-001": {
        "raw_text": (
            "Berater: Guten Tag, Herr Mustermann. Was kann ich für Sie tun? "
            "Kunde: Ich möchte meine Familie absichern, vor allem für den Todesfall. "
            "Berater: Verstehe. Wie lange planen Sie die Absicherung? "
            "Kunde: Mindestens 20 Jahre. Berater: Ihr monatliches Budget? "
            "Kunde: Maximal 80 Euro. Berater: Ich empfehle OVB Life Premium – "
            "30 Euro monatlich, 20 Jahre Laufzeit. Risiko: kein Rückkaufswert. "
            "Datum: 2025-03-15."
        ),
        "entities": {
            "kundenwunsch": "Absicherung der Familie im Todesfall",
            "bedarfsanalyse": "Todesfallabsicherung, Horizont 20 Jahre, Budget max. 80 EUR/Monat",
            "empfehlung": "OVB Life Premium",
            "begruendung": "Passt zu Kundenwunsch und Budget",
            "risikohinweise": "Kein Rückkaufswert bei vorzeitiger Kündigung",
            "produktbezeichnung": "OVB Life Premium",
            "praemie_eur": 30.0,
            "laufzeit_jahre": 20,
            "beratungsdatum": "2025-03-15",
        },
    },
    "TRANS-002": {
        # Deliberately incomplete transcript – missing Risikohinweise and Begründung
        "raw_text": (
            "Berater: Hallo Frau Schmidt. Kunde: Ich brauche eine Altersvorsorge. "
            "Berater: Ich empfehle OVB Pension Classic, 100 Euro monatlich, 15 Jahre. "
            "Datum: 2025-04-01."
        ),
        "entities": {
            "kundenwunsch": "Altersvorsorge",
            "bedarfsanalyse": None,   # missing
            "empfehlung": "OVB Pension Classic",
            "begruendung": None,      # missing
            "risikohinweise": None,   # missing
            "produktbezeichnung": "OVB Pension Classic",
            "praemie_eur": 100.0,
            "laufzeit_jahre": 15,
            "beratungsdatum": "2025-04-01",
        },
    },
    "TRANS-003": {
        # Transcript with a hallucination trap: Kunde never mentioned a specific return rate
        "raw_text": (
            "Berater: Guten Tag, Herr Neukunde. Kunde: Ich interessiere mich für "
            "Kapitalanlage mit hohem Risiko. Berater: Gut, FIN-INVEST-GROWTH könnte passen. "
            "Risiken: Kapitalverlust möglich. Datum: 2025-05-10."
        ),
        "entities": {
            "kundenwunsch": "Kapitalanlage mit hohem Risikoprofil",
            "bedarfsanalyse": "Hochrisiko-Anlage",
            "empfehlung": "FIN-INVEST-GROWTH",
            "begruendung": "Entspricht Kundenpräferenz für hohes Risiko",
            "risikohinweise": "Kapitalverlust möglich",
            "produktbezeichnung": "FIN-INVEST-GROWTH",
            "praemie_eur": None,   # never discussed
            "laufzeit_jahre": None,  # never discussed
            "beratungsdatum": "2025-05-10",
        },
    },
    "TRANS-004": {
        # Noch keine Produktentscheidung getroffen – anderer Fehlkombinations-Fall als TRANS-002/003
        "raw_text": (
            "Berater: Guten Tag, Herr Weber. Was führt Sie zu uns? "
            "Kunde: Ich bin Dachdecker und möchte mich gegen Berufsunfähigkeit absichern, "
            "am liebsten mit einer BU-Rente ab 60 Prozent Invalidität. Berater: Verstehe, "
            "bei handwerklicher Tätigkeit gibt es eine Wartezeit von 3 Jahren bei "
            "Vorerkrankungen. Ich muss die passenden Tarife erst intern prüfen und melde "
            "mich mit einem konkreten Vorschlag. Laufzeit wäre in jedem Fall 25 Jahre. "
            "Datum: 2025-06-02."
        ),
        "entities": {
            "kundenwunsch": "Berufsunfähigkeitsabsicherung bei handwerklicher Tätigkeit",
            "bedarfsanalyse": (
                "Dachdecker, BU-Rente ab 60% Invalidität gewünscht, Laufzeit 25 Jahre"
            ),
            "empfehlung": None,       # noch keine Produktentscheidung getroffen
            "begruendung": None,      # kann ohne Empfehlung nicht existieren
            "risikohinweise": "Wartezeit von 3 Jahren bei Vorerkrankungen",
            "produktbezeichnung": None,  # noch offen
            "praemie_eur": None,      # hängt vom noch offenen Produkt ab
            "laufzeit_jahre": 25,
            "beratungsdatum": "2025-06-02",
        },
    },
    "TRANS-005": {
        # Nahezu leeres Erstgespräch – nur allgemeines Interesse, keine Beratung erfolgt
        "raw_text": (
            "Berater: Guten Tag, wie kann ich helfen? Kunde: Ich wollte mich nur mal "
            "allgemein über Altersvorsorge informieren, habe aber noch keine konkreten "
            "Vorstellungen. Berater: Kein Problem, dann vereinbaren wir einen "
            "ausführlichen Termin für nächste Woche. Datum: 2025-06-10."
        ),
        "entities": {
            "kundenwunsch": "Allgemeines Interesse an Altersvorsorge, keine konkrete Bedarfsklärung",
            "bedarfsanalyse": None,
            "empfehlung": None,
            "begruendung": None,
            "risikohinweise": None,
            "produktbezeichnung": None,
            "praemie_eur": None,
            "laufzeit_jahre": None,
            "beratungsdatum": "2025-06-10",
        },
    },
    "TRANS-006": {
        # Zwei Produkte im Gespräch verglichen, nur eines tatsächlich empfohlen – Ablenker für Halluzination
        "raw_text": (
            "Berater: Ich zeige Ihnen zwei Optionen: OVB Life Premium für 30 Euro und "
            "OVB Life Basic für 22 Euro monatlich. Kunde: 30 Euro ist mir zu teuer, ich "
            "nehme die günstigere Variante. Berater: Gut, dann empfehle ich OVB Life Basic, "
            "20 Jahre Laufzeit. Die Todesfallsumme ist etwas niedriger als bei Premium. "
            "Datum: 2025-06-18."
        ),
        "entities": {
            "kundenwunsch": "Kostengünstige Risikolebensversicherung",
            "bedarfsanalyse": (
                "Vergleich zwischen OVB Life Premium und OVB Life Basic, Budget max. 25 EUR/Monat"
            ),
            "empfehlung": "OVB Life Basic",
            "begruendung": "Erfüllt Budgetvorgabe; OVB Life Premium wäre mit 30 EUR zu teuer gewesen",
            "risikohinweise": "Geringere Todesfallsumme als bei der Premium-Variante",
            "produktbezeichnung": "OVB Life Basic",
            "praemie_eur": 22.0,
            "laufzeit_jahre": 20,
            "beratungsdatum": "2025-06-18",
        },
    },
}


# ─── Tool-Definitionen ────────────────────────────────────────────────────────

@tool
def extract_dialogue_entities(transcript_id: str) -> dict:
    """
    Extrahiert strukturierte Entitäten aus einem Beratungsgespräch-Transkript.
    Gibt alle erkannten §61-VVG-relevanten Felder zurück.
    Fehlende oder nicht besprochene Felder werden als None gekennzeichnet.
    """
    transcript = TRANSCRIPT_DB.get(transcript_id)
    if not transcript:
        return {
            "error": f"Transkript '{transcript_id}' nicht gefunden.",
            "available_transcripts": list(TRANSCRIPT_DB.keys()),
        }
    entities = transcript["entities"]
    missing = [k for k, v in entities.items() if v is None]
    result = {
        "transcript_id": transcript_id,
        "entities": entities,
    }
    if missing:
        result["incomplete_fields"] = missing
    return result


@tool
def check_required_fields(entities: dict) -> dict:
    """
    Prüft ob alle §61-VVG-Pflichtfelder im Beratungsprotokoll vorhanden sind.
    Gibt eine Liste fehlender Pflichtfelder zurück.
    Ein vollständiges Protokoll erfordert alle 9 Pflichtfelder.
    """
    missing = [field for field in VVG_REQUIRED_FIELDS if not entities.get(field)]
    present = [field for field in VVG_REQUIRED_FIELDS if entities.get(field)]

    return {
        "compliant": len(missing) == 0,
        "present_fields": present,
        "missing_fields": missing,
        "completeness_pct": round(len(present) / len(VVG_REQUIRED_FIELDS) * 100),
        "regulatory_basis": "§61 VVG – Pflicht zur Dokumentation der Beratung",
    }


@tool
def generate_protocol(entities: dict, transcript_id: str) -> dict:
    """
    Erstellt ein strukturiertes Beratungsprotokoll nach §61 VVG aus den extrahierten Entitäten.
    Enthält nur Informationen, die tatsächlich aus dem Transkript extrahiert wurden.
    Fehlende Pflichtfelder werden im Protokoll als [FEHLT – NACHTRAG ERFORDERLICH] markiert.
    """
    def val(key):
        v = entities.get(key)
        return v if v is not None else "[FEHLT – NACHTRAG ERFORDERLICH]"

    protocol = {
        "dokument_typ": "Beratungsprotokoll gemäß §61 VVG",
        "transcript_id": transcript_id,
        "beratungsdatum": val("beratungsdatum"),
        "abschnitt_1_kundenwunsch": {
            "kundenwunsch": val("kundenwunsch"),
            "bedarfsanalyse": val("bedarfsanalyse"),
        },
        "abschnitt_2_empfehlung": {
            "produktbezeichnung": val("produktbezeichnung"),
            "empfehlung": val("empfehlung"),
            "begruendung": val("begruendung"),
        },
        "abschnitt_3_konditionen": {
            "praemie_eur_monatlich": val("praemie_eur"),
            "laufzeit_jahre": val("laufzeit_jahre"),
        },
        "abschnitt_4_risikohinweise": {
            "risikohinweise": val("risikohinweise"),
        },
        "hinweis": (
            "Dieses Protokoll wurde aus dem Beratungsgespräch automatisch erstellt. "
            "Mit '[FEHLT]' markierte Felder müssen vom Berater nachgepflegt werden. "
            "§61 VVG-Konformität erst nach Vervollständigung gegeben."
        ),
    }

    missing = [f for f in VVG_REQUIRED_FIELDS if not entities.get(f)]
    protocol["vvg_compliant"] = len(missing) == 0
    if missing:
        protocol["missing_fields"] = missing

    return protocol


@tool
def flag_missing_information(transcript_id: str, missing_fields: list) -> dict:
    """
    Meldet fehlende Pflichtfelder an den Berater zur Nachpflege.
    Gibt eine strukturierte Nachpflege-Anforderung mit Frist zurück.
    Pflichtschritt wenn check_required_fields fehlende Felder ausweist.
    """
    if not missing_fields:
        return {
            "status": "vollständig",
            "message": "Alle §61-VVG-Pflichtfelder vorhanden. Kein Nachtrag erforderlich.",
        }

    field_descriptions = {
        "bedarfsanalyse": "Analyse der Kundenbedürfnisse und finanziellen Situation",
        "begruendung": "Begründung warum das empfohlene Produkt geeignet ist",
        "risikohinweise": "Hinweise zu Risiken des empfohlenen Produkts",
        "praemie_eur": "Monatliche Prämie in EUR",
        "laufzeit_jahre": "Vertragslaufzeit in Jahren",
        "kundenwunsch": "Vom Kunden geäußerter Wunsch / Beratungsanlass",
        "produktbezeichnung": "Exakte Bezeichnung des empfohlenen Produkts",
        "empfehlung": "Konkrete Produktempfehlung des Beraters",
        "beratungsdatum": "Datum des Beratungsgesprächs",
    }

    items = []
    for field in missing_fields:
        items.append({
            "field": field,
            "description": field_descriptions.get(field, field),
            "required_by": "§61 VVG",
        })

    return {
        "transcript_id": transcript_id,
        "flagged": True,
        "missing_count": len(missing_fields),
        "nachpflege_items": items,
        "frist": "5 Werktage",
        "regulatory_basis": "§61 VVG – Protokollierungspflicht vor Vertragsschluss",
        "message": (
            f"{len(missing_fields)} Pflichtfeld(er) fehlen. "
            "Berater muss innerhalb von 5 Werktagen nachpflegen."
        ),
    }


TOOLS = [extract_dialogue_entities, check_required_fields, generate_protocol, flag_missing_information]
