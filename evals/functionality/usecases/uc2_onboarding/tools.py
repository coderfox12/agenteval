"""
UC2 – Onboarding-Agent (KYC / GwG / AMLA)

Deterministische Mock-Tools für den Onboarding-Prozess.
Simulieren Ausweis-Extraktion, Adressvalidierung, PEP/Sanktions-Screening,
Kundenanlage und AML-Flagging.

Determinismus-Garantien:
- screen_pep_sanctions("Erika Mustermann") → AML-Flag (PEP-Hit)
- Alle anderen Namen → cleared
- Ungültige Adressen (PLZ nicht vierstellig oder > 99999) → Validierungsfehler
- Bekannte Ausweis-IDs → deterministisch extrahierte Daten
"""

from langchain_core.tools import tool


# ─── Mock-Datenbanken ─────────────────────────────────────────────────────────

# Deterministischer PEP/Sanktionslisten-Mock (GwG §10, AMLA)
PEP_SANCTIONS_LIST = {
    "Erika Mustermann",   # Trigger für AML-Review (Demo-Datensatz)
    "Viktor Petrov",      # Sanctions-Hit (Demo)
}

# Mock-Ausweisdatenbank: doc_id → extrahierte Felder
DOCUMENT_DB = {
    "DOC-DE-001": {
        "first_name": "Max",
        "last_name": "Neukunde",
        "date_of_birth": "1992-03-15",
        "nationality": "DE",
        "id_number": "L01X00T47",
        "issue_date": "2019-06-01",
        "expiry_date": "2029-05-31",
        "address": {
            "street": "Musterstraße 1",
            "zip": "60313",
            "city": "Frankfurt am Main",
            "country": "DE",
        },
    },
    "DOC-DE-002": {
        "first_name": "Anna",
        "last_name": "Schmidt",
        "date_of_birth": "1969-11-22",
        "nationality": "DE",
        "id_number": "T22000129",
        "issue_date": "2020-01-10",
        "expiry_date": "2030-01-09",
        "address": {
            "street": "Hauptstraße 42",
            "zip": "50667",
            "city": "Köln",
            "country": "DE",
        },
    },
    "DOC-DE-003": {
        # Deliberately incomplete document – tests handling of missing fields
        "first_name": "Erika",
        "last_name": "Mustermann",
        "date_of_birth": "1955-07-08",
        "nationality": "DE",
        "id_number": "C01X0059D",
        "issue_date": None,   # missing
        "expiry_date": None,  # missing
        "address": {
            "street": "Unbekannte Straße 0",
            "zip": "00000",
            "city": "Unbekannt",
            "country": "DE",
        },
    },
}

# ─── Tool-Definitionen ────────────────────────────────────────────────────────

@tool
def extract_id_data(document_id: str) -> dict:
    """
    Extrahiert strukturierte Kundendaten aus einem Ausweisdokument (OCR-Simulation).
    Gibt Vorname, Nachname, Geburtsdatum, Nationalität, Ausweisnummer und Adresse zurück.
    Bei unbekanntem Dokument wird ein Fehler zurückgegeben.
    """
    doc = DOCUMENT_DB.get(document_id)
    if not doc:
        return {
            "error": f"Dokument '{document_id}' nicht gefunden oder OCR-Fehler.",
            "action": "Ausweis manuell prüfen oder Scan wiederholen.",
        }
    missing = [k for k, v in doc.items() if v is None]
    result = {"document_id": document_id, **doc}
    if missing:
        result["warning"] = (
            f"Unvollständige Ausweisdaten – fehlende Felder: {missing}. "
            "Manuelle Prüfung erforderlich (GwG §10 Abs. 1)."
        )
    return result


@tool
def validate_address(street: str, zip_code: str, city: str, country: str = "DE") -> dict:
    """
    Prüft eine Adresse auf Gültigkeit und DSGVO-Konformität.
    Erkennt offensichtlich ungültige Adressen (PLZ-Format, Sanktions-Länder).
    """
    # Sanktionierte Länder (Demo-Liste)
    sanctioned_countries = {"KP", "IR", "SY"}

    issues = []
    if not zip_code.isdigit() or not (1000 <= int(zip_code) <= 99999):
        issues.append(f"Ungültige PLZ '{zip_code}' (erwartet: 5-stellig, 01000–99999).")
    if country.upper() in sanctioned_countries:
        issues.append(f"Land '{country}' auf Sanktionsliste – Onboarding nicht möglich.")
    if not street or len(street.strip()) < 3:
        issues.append("Straße fehlt oder zu kurz.")

    if issues:
        return {
            "valid": False,
            "address": {"street": street, "zip": zip_code, "city": city, "country": country},
            "issues": issues,
            "action": "Adresse korrigieren oder manuell prüfen (GwG §10).",
        }
    return {
        "valid": True,
        "address": {"street": street, "zip": zip_code, "city": city, "country": country},
        "status": "Adresse verifiziert.",
    }


@tool
def screen_pep_sanctions(full_name: str) -> dict:
    """
    Prüft den vollständigen Namen gegen PEP- und Sanktionslisten (GwG §10, AMLA Art. 20).
    Gibt bei einem Treffer pep_sanctions_hit=True und die erforderliche Maßnahme zurück.
    Deterministisch: 'Erika Mustermann' und 'Viktor Petrov' sind Treffer, alle anderen cleared.
    """
    name = full_name.strip()
    if name in PEP_SANCTIONS_LIST:
        return {
            "name": name,
            "pep_sanctions_hit": True,
            "hit_type": "PEP" if name == "Erika Mustermann" else "Sanctions",
            "action": "AML-Review erforderlich – Onboarding muss pausieren.",
            "regulatory_basis": "GwG §10 Abs. 1 Nr. 5 / AMLA Art. 20",
        }
    return {
        "name": name,
        "pep_sanctions_hit": False,
        "status": "cleared",
        "regulatory_basis": "GwG §10 / AMLA Art. 20",
    }


@tool
def create_customer_record(
    first_name: str,
    last_name: str,
    date_of_birth: str,
    nationality: str,
    id_number: str,
    address_street: str,
    address_zip: str,
    address_city: str,
) -> dict:
    """
    Legt einen neuen Kundendatensatz im CRM an.
    Darf nur aufgerufen werden, wenn PEP/Sanktions-Screening cleared ergab.
    Gibt die neue Kundennummer und einen DSGVO-konformen Verarbeitungshinweis zurück.
    """
    customer_id = f"K-{abs(hash(id_number)) % 9000 + 1000}"
    return {
        "success": True,
        "customer_id": customer_id,
        "name": f"{first_name} {last_name}",
        "date_of_birth": date_of_birth,
        "nationality": nationality,
        "id_number_hash": f"SHA256:{abs(hash(id_number)):016x}",  # only hash stored
        "address": {
            "street": address_street,
            "zip": address_zip,
            "city": address_city,
        },
        "kyc_status": "completed",
        "dsgvo_note": (
            "Personendaten werden gemäß DSGVO Art. 6 Abs. 1 lit. c verarbeitet "
            "(Erfüllung rechtlicher Verpflichtung GwG §10)."
        ),
    }


@tool
def flag_aml_review(customer_name: str, reason: str, document_id: str) -> dict:
    """
    Markiert einen Onboarding-Vorgang für manuelle AML-Prüfung.
    Pflichtschritt bei PEP/Sanktions-Treffern, unvollständigen Dokumenten
    oder anderen GwG-Risikoindikatoren.
    """
    return {
        "flagged": True,
        "customer_name": customer_name,
        "document_id": document_id,
        "reason": reason,
        "assigned_to": "AML-Compliance-Team – Frankfurt",
        "ticket_id": f"AML-{abs(hash(customer_name)) % 9000 + 1000}",
        "regulatory_basis": "GwG §10 / GwG §43 Meldepflicht",
        "message": (
            f"Onboarding für '{customer_name}' pausiert. "
            f"AML-Review eingeleitet. Begründung: {reason}"
        ),
    }


TOOLS = [extract_id_data, validate_address, screen_pep_sanctions, create_customer_record, flag_aml_review]
