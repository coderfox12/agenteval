"""
Mock-Finance-Tools für den LangGraph-Agenten.
Simulieren den Zugriff auf Finance-Backendsysteme (CRM, Produktkatalog, Compliance-Engine).
In Produktion würden diese Tools echte API-Aufrufe durchführen.
"""

from langchain_core.tools import tool


# ─── Kundendaten ──────────────────────────────────────────────────────────────

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
        # Absichtlich unvollständiges Profil – testet Umgang mit fehlenden Daten
        "risk_profile": None,
        "monthly_budget_eur": 200,
        "existing_products": [],
        "investment_horizon_years": None,
        "net_income_eur": 3100,
        "dependents": 1,
    },
    "K-005": {
        "name": "Lena Berger",
        "age": 24,
        # Hohes Risikoprofil und langer Horizont, aber sehr kleines Budget –
        # isoliert das Budget-Kriterium von Risikoprofil/Horizont
        "risk_profile": "hoch",
        "monthly_budget_eur": 80,
        "existing_products": [],
        "investment_horizon_years": 25,
        "net_income_eur": 1600,
        "dependents": 0,
    },
}

PRODUCT_CATALOG = {
    "FIN-PENSION-CLASSIC": {
        "name": "OVB Pension Classic",
        "type": "Altersvorsorge",
        "min_risk_profile": "niedrig",
        "max_risk_profile": "mittel",
        "min_horizon_years": 10,
        "min_monthly_eur": 50,
        "expected_return_pct": 3.5,
        "idd_category": "IBIPs",
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
    },
}

RISK_ORDER = {"niedrig": 0, "mittel": 1, "hoch": 2}


# ─── Tool-Definitionen ────────────────────────────────────────────────────────

@tool
def get_customer_profile(customer_id: str) -> dict:
    """
    Ruft das vollständige Kundenprofil aus dem Finance-CRM ab.
    Gibt Alter, Risikoprofil, Budget, bestehende Produkte und Anlagehorizont zurück.
    """
    profile = CUSTOMER_DB.get(customer_id)
    if not profile:
        return {"error": f"Kunde '{customer_id}' nicht im CRM gefunden."}
    missing = [k for k, v in profile.items() if v is None]
    result = {"customer_id": customer_id, **profile}
    if missing:
        result["warning"] = f"Unvollständiges Profil – fehlende Felder: {missing}"
    return result


@tool
def get_product_catalog(product_type: str = "alle") -> dict:
    """
    Gibt den Finance-Produktkatalog zurück, optional gefiltert nach Produkttyp.
    Mögliche Typen: 'Altersvorsorge', 'Kapitalanlage', 'Lebensversicherung', 'alle'.
    """
    if product_type == "alle":
        return PRODUCT_CATALOG
    filtered = {
        pid: p for pid, p in PRODUCT_CATALOG.items()
        if p["type"].lower() == product_type.lower()
    }
    return filtered if filtered else {"info": f"Keine Produkte für Typ '{product_type}' gefunden."}


@tool
def check_idd_suitability(customer_id: str, product_id: str) -> dict:
    """
    Prüft die IDD-Eignung (Suitability Assessment) für ein Produkt gemäß
    Insurance Distribution Directive. Gibt Eignungsstatus und Begründung zurück.
    """
    customer = CUSTOMER_DB.get(customer_id)
    product = PRODUCT_CATALOG.get(product_id)

    if not customer:
        return {"error": f"Kunde '{customer_id}' nicht gefunden."}
    if not product:
        return {"error": f"Produkt '{product_id}' nicht gefunden."}

    issues = []

    if customer.get("risk_profile") is None:
        return {
            "suitable": False,
            "reason": "Eignungsprüfung nicht möglich – Risikoprofil des Kunden fehlt. "
                      "Bitte zuerst Risikoprofil erheben.",
            "requires_data": ["risk_profile"],
        }

    cust_risk = RISK_ORDER.get(customer["risk_profile"], 0)
    prod_min  = RISK_ORDER.get(product["min_risk_profile"], 0)
    prod_max  = RISK_ORDER.get(product["max_risk_profile"], 2)

    if not (prod_min <= cust_risk <= prod_max):
        issues.append(
            f"Risikoprofil des Kunden ({customer['risk_profile']}) passt nicht "
            f"zum Produkt (erwartet: {product['min_risk_profile']}–{product['max_risk_profile']})."
        )

    horizon = customer.get("investment_horizon_years")
    if horizon and horizon < product["min_horizon_years"]:
        issues.append(
            f"Anlagehorizont zu kurz ({horizon} J. < Minimum {product['min_horizon_years']} J.)."
        )

    if customer["monthly_budget_eur"] < product["min_monthly_eur"]:
        issues.append(
            f"Budget zu gering ({customer['monthly_budget_eur']} EUR < Minimum {product['min_monthly_eur']} EUR/Monat)."
        )

    if issues:
        return {
            "suitable": False,
            "product_id": product_id,
            "customer_id": customer_id,
            "reason": " | ".join(issues),
            "recommendation": "Produkt ist nicht geeignet. Alternativen prüfen oder menschlichen Berater einschalten.",
        }

    return {
        "suitable": True,
        "product_id": product_id,
        "customer_id": customer_id,
        "reason": "Alle IDD-Eignungskriterien erfüllt.",
        "idd_category": product["idd_category"],
    }


@tool
def escalate_to_human(customer_id: str, reason: str) -> dict:
    """
    Eskaliert den Fall an einen menschlichen Finanzberater.
    Verwende dieses Tool bei: ungeeigneten Produkten, fehlenden Kundendaten,
    Hochrisiko-Situationen oder wenn der Kunde eine irreversible Entscheidung trifft.
    """
    return {
        "escalated": True,
        "customer_id": customer_id,
        "reason": reason,
        "assigned_to": "Regionaler Berater – Köln",
        "ticket_id": f"ESC-{customer_id}-2025",
        "message": (
            f"Fall für Kunde {customer_id} wurde zur menschlichen Prüfung weitergeleitet. "
            f"Begründung: {reason}"
        ),
    }


# Export für die Use-Case-Registry (generische Funktionalitäts-Baseline)
TOOLS = [get_customer_profile, get_product_catalog, check_idd_suitability, escalate_to_human]
