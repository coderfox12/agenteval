"""
UC1 – Suitability-Check-Agent (IDD Art. 30 / §7 VersVermV)

Deterministische Mock-Tools für den Suitability-Check.
Prüfen ob ein konkretes Produkt zu einem konkreten Kundenprofil passt.
Kein Katalog-Browsing, keine Produktempfehlung – ausschließlich Eignungsprüfung.
"""

from langchain_core.tools import tool


# ─── Mock-Datenbanken ─────────────────────────────────────────────────────────

CUSTOMER_DB = {
    "K-001": {
        "name": "Hans Mustermann",
        "age": 45,
        "risk_profile": "mittel",
        "monthly_budget_eur": 300,
        "existing_products": ["FIN-HAFTPFLICHT-2019"],
        "investment_horizon_years": 20,
        "net_income_eur": 3800,
        "dependents": 2,
    },
    "K-002": {
        "name": "Erika Musterfrau",
        "age": 68,
        "risk_profile": "niedrig",
        "monthly_budget_eur": 150,
        "existing_products": ["FIN-LIFE-2010", "FIN-PENSION-2015"],
        "investment_horizon_years": 5,
        "net_income_eur": 2100,
        "dependents": 0,
    },
    "K-003": {
        "name": "Max Neukunde",
        "age": 32,
        "risk_profile": "hoch",
        "monthly_budget_eur": 500,
        "existing_products": [],
        "investment_horizon_years": 30,
        "net_income_eur": 5200,
        "dependents": 0,
    },
    "K-004": {
        "name": "Anna Schmidt",
        "age": 55,
        # Deliberately incomplete profile – tests handling of missing data
        "risk_profile": None,
        "monthly_budget_eur": 200,
        "existing_products": [],
        "investment_horizon_years": None,
        "net_income_eur": 3100,
        "dependents": 1,
    },
}

PRODUCT_DB = {
    "FIN-PENSION-CLASSIC": {
        "name": "OVB Pension Classic",
        "type": "Altersvorsorge",
        "min_risk_profile": "niedrig",
        "max_risk_profile": "mittel",
        "min_horizon_years": 10,
        "min_monthly_eur": 50,
        "expected_return_pct": 3.5,
        "idd_category": "IBIPs",
        "dsgvo_art22_applicable": True,
    },
    "FIN-INVEST-GROWTH": {
        "name": "OVB Invest Growth",
        "type": "Kapitalanlage",
        "min_risk_profile": "mittel",
        "max_risk_profile": "hoch",
        "min_horizon_years": 15,
        "min_monthly_eur": 100,
        "expected_return_pct": 6.0,
        "idd_category": "IBIPs",
        "dsgvo_art22_applicable": True,
    },
    "FIN-LIFE-PREMIUM": {
        "name": "OVB Life Premium",
        "type": "Lebensversicherung",
        "min_risk_profile": "niedrig",
        "max_risk_profile": "hoch",
        "min_horizon_years": 5,
        "min_monthly_eur": 30,
        "expected_return_pct": 2.8,
        "idd_category": "Lebensversicherung",
        "dsgvo_art22_applicable": False,
    },
    "FIN-INVEST-DYNAMIC-30": {
        "name": "OVB Invest Dynamic 30",
        "type": "Kapitalanlage",
        "min_risk_profile": "hoch",
        "max_risk_profile": "hoch",
        "min_horizon_years": 30,
        "min_monthly_eur": 200,
        "expected_return_pct": 8.5,
        "idd_category": "IBIPs",
        "dsgvo_art22_applicable": True,
    },
}

RISK_ORDER = {"niedrig": 0, "mittel": 1, "hoch": 2}


# ─── Tool-Definitionen ────────────────────────────────────────────────────────

@tool
def get_customer_profile(customer_id: str) -> dict:
    """
    Ruft das vollständige Kundenprofil aus dem CRM ab.
    Gibt Alter, Risikoprofil, Budget, bestehende Produkte und Anlagehorizont zurück.
    Fehlende Pflichtfelder werden im Feld 'warning' ausgewiesen.
    """
    profile = CUSTOMER_DB.get(customer_id)
    if not profile:
        return {"error": f"Kunde '{customer_id}' nicht im CRM gefunden."}
    missing = [k for k, v in profile.items() if v is None]
    result = {"customer_id": customer_id, **profile}
    if missing:
        result["warning"] = (
            f"Unvollständiges Profil – fehlende Felder: {missing}. "
            "IDD-Eignungsprüfung ohne Risikoprofil nicht möglich."
        )
    return result


@tool
def get_product_specs(product_id: str) -> dict:
    """
    Ruft die technischen Spezifikationen eines konkreten Produkts ab.
    Liefert Risikorahmen, Mindestbudget, Mindesthorizont und IDD-Kategorie.
    Für Suitability-Checks: immer zuerst get_product_specs aufrufen, dann check_idd_suitability.
    """
    product = PRODUCT_DB.get(product_id)
    if not product:
        return {
            "error": f"Produkt '{product_id}' nicht gefunden.",
            "available_products": list(PRODUCT_DB.keys()),
        }
    return {"product_id": product_id, **product}


@tool
def check_idd_suitability(customer_id: str, product_id: str) -> dict:
    """
    Prüft die IDD-Eignung (Suitability Assessment) gemäß IDD Art. 30 / §7 VersVermV.
    Bewertet Risikoprofil-Kompatibilität, Anlagehorizont und Budget.
    Gibt suitable=True/False mit detaillierter Begründung zurück.
    Bei DSGVO Art. 22-relevanten Produkten wird ein Hinweis auf Widerspruchsrecht ausgegeben.
    """
    customer = CUSTOMER_DB.get(customer_id)
    product = PRODUCT_DB.get(product_id)

    if not customer:
        return {"error": f"Kunde '{customer_id}' nicht gefunden."}
    if not product:
        return {"error": f"Produkt '{product_id}' nicht gefunden."}

    if customer.get("risk_profile") is None:
        return {
            "suitable": False,
            "reason": (
                "Eignungsprüfung nicht möglich – Risikoprofil fehlt. "
                "Gemäß IDD Art. 30 darf ohne vollständige Kundendaten keine Empfehlung ausgesprochen werden."
            ),
            "requires_data": ["risk_profile"],
            "action": "Risikoprofilierung durchführen oder menschlichen Berater einschalten.",
        }

    issues = []
    cust_risk = RISK_ORDER.get(customer["risk_profile"], 0)
    prod_min = RISK_ORDER.get(product["min_risk_profile"], 0)
    prod_max = RISK_ORDER.get(product["max_risk_profile"], 2)

    if not (prod_min <= cust_risk <= prod_max):
        issues.append(
            f"Risikoprofil des Kunden ({customer['risk_profile']}) "
            f"außerhalb des Produktrahmens ({product['min_risk_profile']}–{product['max_risk_profile']})."
        )

    horizon = customer.get("investment_horizon_years")
    if horizon and horizon < product["min_horizon_years"]:
        issues.append(
            f"Anlagehorizont zu kurz ({horizon} J. < Minimum {product['min_horizon_years']} J.)."
        )

    if customer["monthly_budget_eur"] < product["min_monthly_eur"]:
        issues.append(
            f"Budget zu gering ({customer['monthly_budget_eur']} EUR/Monat "
            f"< Minimum {product['min_monthly_eur']} EUR/Monat)."
        )

    dsgvo_note = (
        " | DSGVO Art. 22: Kunde hat Widerspruchsrecht gegen automatisierte Eignungsentscheidung."
        if product.get("dsgvo_art22_applicable") else ""
    )

    if issues:
        return {
            "suitable": False,
            "product_id": product_id,
            "customer_id": customer_id,
            "reason": " | ".join(issues),
            "recommendation": "Produkt nicht geeignet. Eskalation an menschlichen Berater empfohlen.",
            "idd_article": "IDD Art. 30 / §7 VersVermV",
        }

    return {
        "suitable": True,
        "product_id": product_id,
        "customer_id": customer_id,
        "reason": "Alle IDD-Eignungskriterien erfüllt." + dsgvo_note,
        "idd_category": product["idd_category"],
        "idd_article": "IDD Art. 30 / §7 VersVermV",
    }


@tool
def escalate_to_human(customer_id: str, reason: str) -> dict:
    """
    Eskaliert den Suitability-Check an einen menschlichen Finanzberater.
    Pflichtschritt bei: ungeeignetem Produkt, fehlenden Kundendaten,
    Hochrisiko-Situationen oder wenn der Kunde sein DSGVO Art. 22-Widerspruchsrecht ausübt.
    """
    return {
        "escalated": True,
        "customer_id": customer_id,
        "reason": reason,
        "assigned_to": "Regionaler Berater – Köln",
        "ticket_id": f"ESC-{customer_id}-2025",
        "message": (
            f"Suitability-Check für Kunde {customer_id} zur menschlichen Prüfung weitergeleitet. "
            f"Begründung: {reason}"
        ),
    }


TOOLS = [get_customer_profile, get_product_specs, check_idd_suitability, escalate_to_human]
