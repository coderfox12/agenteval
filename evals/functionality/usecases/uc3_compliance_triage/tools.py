"""
UC3 – Compliance-Triage-Agent (EU AI Act / OVB-Governance)

Deterministische Mock-Tools für den KI-Self-Check.
Simulieren einen RAG-gestützten Regulatorik-Korpus, Risikoklassifizierung,
Governance-Matching und Maßnahmenlistengenerierung.

Deterministisch: jede Tool-Antwort ist für gegebene Inputs fest.
Zitationstreue ist der zentrale Evaluierungsaspekt (FaithfulnessMetric):
retrieve_regulatory_corpus gibt immer Passagen MIT Quellen-IDs zurück.
"""

from langchain_core.tools import tool


# ─── Regulatorik-Korpus (Mini-RAG) ────────────────────────────────────────────
# Jeder Eintrag: query_keywords → Liste von Passagen mit source_id
# Der Agent soll Quellen-IDs in Antworten zitieren – Grundlage für FaithfulnessMetric.

REGULATORY_CORPUS = {
    "high_risk": [
        {
            "source_id": "EU-AI-Act/Annex-III/Nr.5",
            "text": (
                "Annex III Nr. 5 EU AI Act: KI-Systeme, die in der Beschäftigung, "
                "im Personalmanagement und beim Zugang zur Selbstständigkeit eingesetzt werden, "
                "insbesondere für Bewerbungsverfahren oder Einstellungsentscheidungen, "
                "gelten als Hochrisiko-KI-Systeme."
            ),
        },
        {
            "source_id": "EU-AI-Act/Art.10",
            "text": (
                "Art. 10 EU AI Act: Anbieter von Hochrisiko-KI-Systemen müssen "
                "Datenverwaltungs- und Governance-Praktiken für Trainingsdaten einhalten."
            ),
        },
        {
            "source_id": "EU-AI-Act/Art.13",
            "text": (
                "Art. 13 EU AI Act: Hochrisiko-KI-Systeme müssen so konzipiert sein, "
                "dass ihre Funktionsweise hinreichend transparent ist, damit Nutzer "
                "die Ausgaben des Systems verstehen und angemessen nutzen können."
            ),
        },
        {
            "source_id": "EU-AI-Act/Art.14",
            "text": (
                "Art. 14 EU AI Act: Hochrisiko-KI-Systeme müssen so konzipiert sein, "
                "dass sie während ihrer Betriebsdauer wirksam von natürlichen Personen "
                "überwacht werden können."
            ),
        },
    ],
    "limited_risk": [
        {
            "source_id": "EU-AI-Act/Art.52",
            "text": (
                "Art. 52 EU AI Act: KI-Systeme mit begrenztem Risiko unterliegen "
                "Transparenzpflichten. Natürliche Personen müssen darüber informiert werden, "
                "dass sie mit einem KI-System interagieren."
            ),
        },
    ],
    "minimal_risk": [
        {
            "source_id": "EU-AI-Act/Erwägungsgrund-47",
            "text": (
                "Erwägungsgrund 47 EU AI Act: KI-Systeme mit minimalem Risiko, "
                "wie Spam-Filter oder KI in Videospielen, können frei entwickelt und "
                "eingesetzt werden. Es gibt keine verbindlichen Anforderungen."
            ),
        },
    ],
    "financial_services": [
        {
            "source_id": "EU-AI-Act/Annex-III/Nr.5b",
            "text": (
                "Annex III Nr. 5b EU AI Act: KI-Systeme zur Kreditwürdigkeitsprüfung "
                "und Bonitätsbewertung natürlicher Personen gelten als Hochrisiko."
            ),
        },
        {
            "source_id": "DSGVO/Art.22",
            "text": (
                "DSGVO Art. 22: Betroffene Personen haben das Recht, nicht einer "
                "ausschließlich auf einer automatisierten Verarbeitung beruhenden Entscheidung "
                "unterworfen zu werden, die ihnen gegenüber rechtliche Wirkung entfaltet."
            ),
        },
    ],
    "ovb_governance": [
        {
            "source_id": "OVB-AI-Policy/v1.2/§3",
            "text": (
                "OVB KI-Governance-Policy §3: Jede KI-Anwendung mit Kundenkontakt "
                "oder regulatorischer Relevanz muss vor Produktiveinsatz durch das "
                "OVB AI-Review-Board genehmigt werden."
            ),
        },
        {
            "source_id": "OVB-AI-Policy/v1.2/§7",
            "text": (
                "OVB KI-Governance-Policy §7: Hochrisiko-KI-Systeme gemäß EU AI Act "
                "erfordern eine Folgenabschätzung und eine Registrierung in der EU-Datenbank."
            ),
        },
    ],
}

# Ground-Truth-Mapping: Anwendungsbeschreibungs-Keywords → Risikolevel
RISK_CLASSIFICATION_DB = {
    "credit_scoring": "high_risk",
    "kreditwürdigkeitsprüfung": "high_risk",
    "bonitätsbewertung": "high_risk",
    "recruitment": "high_risk",
    "einstellungsentscheidung": "high_risk",
    "personalauswahl": "high_risk",
    "chatbot": "limited_risk",
    "kundendialog": "limited_risk",
    "spam_filter": "minimal_risk",
    "produktempfehlung": "limited_risk",
    "beratungsassistent": "limited_risk",
    "suitability_check": "high_risk",
    "eignungsprüfung": "high_risk",
}

GOVERNANCE_POLICIES = {
    "high_risk": {
        "policy_id": "OVB-AI-POL-HIGH",
        "requirements": [
            "AI-Review-Board-Genehmigung (OVB-AI-Policy §3)",
            "Folgenabschätzung durchführen (EU AI Act Art. 9)",
            "Registrierung in EU-AI-Act-Datenbank (Art. 49)",
            "Technische Dokumentation erstellen (Art. 11)",
            "Mensch-in-der-Schleife sicherstellen (Art. 14)",
            "Transparenz gegenüber Nutzern (Art. 13)",
        ],
        "estimated_timeline_weeks": 12,
    },
    "limited_risk": {
        "policy_id": "OVB-AI-POL-LIMITED",
        "requirements": [
            "KI-Kennzeichnungspflicht umsetzen (EU AI Act Art. 52)",
            "Datenschutz-Folgenabschätzung prüfen (DSGVO Art. 35)",
            "Interne Freigabe einholen (OVB-AI-Policy §3)",
        ],
        "estimated_timeline_weeks": 4,
    },
    "minimal_risk": {
        "policy_id": "OVB-AI-POL-MINIMAL",
        "requirements": [
            "Keine verbindlichen EU-AI-Act-Anforderungen",
            "Interne Best-Practice-Richtlinien beachten",
        ],
        "estimated_timeline_weeks": 1,
    },
}


# ─── Tool-Definitionen ────────────────────────────────────────────────────────

@tool
def retrieve_regulatory_corpus(query: str) -> dict:
    """
    Durchsucht den Regulatorik-Korpus (EU AI Act, DSGVO, OVB-Governance) nach relevanten Passagen.
    Gibt Passagen MIT Quellen-IDs zurück – diese müssen in der Antwort zitiert werden.
    Unterstützte Query-Bereiche: high_risk, limited_risk, minimal_risk, financial_services,
    ovb_governance.
    """
    query_lower = query.lower()

    # Keyword-Matching auf Korpus-Kategorien
    selected = []
    if any(k in query_lower for k in ["hochrisiko", "high risk", "high_risk", "annex iii", "annex3"]):
        selected.extend(REGULATORY_CORPUS["high_risk"])
    if any(k in query_lower for k in ["finanz", "kredit", "financial", "versicherung", "suitability"]):
        selected.extend(REGULATORY_CORPUS["financial_services"])
    if any(k in query_lower for k in ["limited", "begrenzt", "chatbot", "transparenz"]):
        selected.extend(REGULATORY_CORPUS["limited_risk"])
    if any(k in query_lower for k in ["minimal", "gering", "spam"]):
        selected.extend(REGULATORY_CORPUS["minimal_risk"])
    if any(k in query_lower for k in ["ovb", "governance", "policy", "intern"]):
        selected.extend(REGULATORY_CORPUS["ovb_governance"])

    # Default: gib relevante Querschnitts-Passagen zurück
    if not selected:
        selected = REGULATORY_CORPUS["high_risk"][:2] + REGULATORY_CORPUS["limited_risk"]

    # Deduplizieren nach source_id
    seen = set()
    unique = []
    for p in selected:
        if p["source_id"] not in seen:
            seen.add(p["source_id"])
            unique.append(p)

    return {
        "query": query,
        "passages": unique,
        "source_ids": [p["source_id"] for p in unique],
        "note": "Quellen-IDs müssen in der finalen Antwort zitiert werden.",
    }


@tool
def classify_risk_level(application_description: str) -> dict:
    """
    Klassifiziert das Risikolevel einer KI-Anwendung gemäß EU AI Act.
    Gibt high_risk, limited_risk oder minimal_risk zurück.
    Deterministisch: bekannte Anwendungstypen werden fest klassifiziert.
    """
    desc_lower = application_description.lower()

    detected_level = "minimal_risk"  # safe default
    matched_keywords = []

    for keyword, level in RISK_CLASSIFICATION_DB.items():
        if keyword in desc_lower:
            matched_keywords.append(keyword)
            if level == "high_risk":
                detected_level = "high_risk"
                break
            elif level == "limited_risk" and detected_level != "high_risk":
                detected_level = "limited_risk"

    return {
        "risk_level": detected_level,
        "matched_keywords": matched_keywords,
        "regulatory_basis": "EU AI Act Annex III / Art. 6",
        "note": (
            "Klassifizierung basiert auf Schlüsselwörtern. "
            "Finale Einstufung erfordert rechtliche Prüfung."
        ),
    }


@tool
def match_governance_policy(risk_level: str) -> dict:
    """
    Gibt die OVB-interne Governance-Policy für das gegebene Risikolevel zurück.
    Listet alle einzuhaltenden Anforderungen mit Rechtsgrundlage und Zeitplan.
    """
    policy = GOVERNANCE_POLICIES.get(risk_level)
    if not policy:
        return {
            "error": f"Unbekanntes Risikolevel '{risk_level}'.",
            "valid_levels": list(GOVERNANCE_POLICIES.keys()),
        }
    return {
        "risk_level": risk_level,
        **policy,
    }


@tool
def generate_action_list(policy_id: str, application_name: str) -> dict:
    """
    Erstellt eine priorisierte Maßnahmenliste für die KI-Anwendung auf Basis der Policy.
    Gibt strukturierte TODO-Einträge mit Verantwortlichkeiten und Fristen zurück.
    """
    policy_map = {p["policy_id"]: (level, p) for level, p in GOVERNANCE_POLICIES.items()}

    if policy_id not in policy_map:
        return {
            "error": f"Policy-ID '{policy_id}' nicht gefunden.",
            "valid_policy_ids": list(policy_map.keys()),
        }

    level, policy = policy_map[policy_id]
    actions = []
    for i, req in enumerate(policy["requirements"], start=1):
        actions.append({
            "priority": i,
            "action": req,
            "responsible": "AI-Compliance-Team" if "Genehmigung" in req or "Registrierung" in req
                           else "Projektverantwortlicher",
            "deadline_weeks": max(1, policy["estimated_timeline_weeks"] // len(policy["requirements"])),
        })

    return {
        "application_name": application_name,
        "policy_id": policy_id,
        "risk_level": level,
        "total_actions": len(actions),
        "actions": actions,
        "estimated_total_weeks": policy["estimated_timeline_weeks"],
    }


TOOLS = [retrieve_regulatory_corpus, classify_risk_level, match_governance_policy, generate_action_list]
