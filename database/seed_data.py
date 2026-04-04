"""
database/seed_data.py
Seeds synthetic policyholders into Cosmos DB (container: policyholders, partition: /member_id).

Run from repo root with Cosmos env set:
  python database/seed_data.py
"""
from __future__ import annotations

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from config import settings

from database.cosmos_client import PolicyholderDB, _database_id, db

FIRST_NAMES = [
    "Sarah", "James", "Aoife", "Ciarán", "Niamh", "Patrick", "Emma", "Seán",
    "Orla", "Liam", "Grace", "Fionn", "Kate", "Declan", "Róisín", "Brian",
    "Maeve", "Conor", "Sinead", "Eoin",
]
LAST_NAMES = [
    "O'Brien", "Murphy", "Kelly", "Walsh", "Brennan", "Ryan", "Byrne", "Doyle",
    "McCarthy", "O'Connell", "Fitzgerald", "Lynch", "O'Neill", "Quinn", "Burke",
    "Power", "Kennedy", "Healy", "Flynn", "Martin",
]
BIRTH_CITIES = [
    "Dublin", "Cork", "Galway", "Limerick", "Waterford", "Kilkenny", "Sligo", "Tralee",
    "Drogheda", "Wexford", "Athlone", "Letterkenny", "Ennis", "Carlow", "Maynooth",
    "Castlebar", "Navan", "Portlaoise", "Mullingar", "Naas",
]
MAIDEN_NAMES = [
    "Walsh", "Kelly", "Murphy", "Ryan", "O'Brien", "Byrne", "Doyle", "McCarthy",
    "Lynch", "Quinn", "Burke", "Power", "Kennedy", "Healy", "Flynn", "Martin",
    "Nolan", "Casey", "Foley", "Sheehan",
]
PLANS = [
    ("PremiumCare Plus", "comprehensive", 500, 100000),
    ("StandardCare", "standard", 1000, 50000),
    ("BasicCare", "basic", 2000, 25000),
    ("SeniorCare Gold", "senior", 250, 150000),
    ("YoungAdult Starter", "basic", 1500, 20000),
]

# Matches tools.identity_tool DEMO_POLICYHOLDERS["POL-001"] for demos + offline fallback parity.
POL_001_JOSHUA = {
    "id": "POL-001",
    "member_id": "POL-001",
    "mem_id": "POL-001",
    "policy_id": "POL-001",
    "policy_number": "POL-001",
    "name": "Joshua",
    "email": "manisham.workmail@gmail.com",
    "dob": "1985-03-14",
    "phone": "+353-87-111-2233",
    "plan_name": "PremiumCare Plus",
    "plan_type": "comprehensive",
    "deductible": 500,
    "deductible_used": 200,
    "annual_limit": 100000,
    "claims_used": 12500,
    "network_tier": 1,
    "policy_blob_prefix": "policy-docs/POL-001/",
    "security_question_1": "What city were you born in?",
    "security_answer_1": "Cork",
    "security_question_2": "What is your mother's maiden name?",
    "security_answer_2": "Walsh",
}


def build_synthetic_policyholders(count: int = 20) -> list[dict]:
    """POL-001 … POL-{count:03d}; emails lowercase; aligns with Blob prefix per policy."""
    rows: list[dict] = []
    for i in range(1, count + 1):
        mid = f"POL-{i:03d}"
        if i == 1:
            rows.append(dict(POL_001_JOSHUA))
            continue

        fn = FIRST_NAMES[(i - 1) % len(FIRST_NAMES)]
        ln = LAST_NAMES[((i - 1) * 3) % len(LAST_NAMES)]
        city = BIRTH_CITIES[(i - 1) % len(BIRTH_CITIES)]
        maiden = MAIDEN_NAMES[(i - 1) % len(MAIDEN_NAMES)]
        plan_name, plan_type, deductible, annual_limit = PLANS[(i - 1) % len(PLANS)]

        yob = 1965 + ((i * 7) % 40)
        month = 1 + ((i * 3) % 12)
        day = 1 + ((i * 5) % 28)
        dob = f"{yob:04d}-{month:02d}-{day:02d}"

        deductible_used = min(deductible, (i * 137) % (deductible + 1))
        claims_used = min(annual_limit - 1000, (i * 1847) % (annual_limit // 2 + 1))

        rows.append(
            {
                "id": mid,
                "member_id": mid,
                "mem_id": mid,
                "policy_id": mid,
                "policy_number": mid,
                "name": f"{fn} {ln}",
                "email": f"member{i:03d}@insureco.demo",
                "phone": f"+353-87-{(1000000 + i * 11111) % 10000000:07d}",
                "dob": dob,
                "plan_name": plan_name,
                "plan_type": plan_type,
                "deductible": deductible,
                "deductible_used": deductible_used,
                "annual_limit": annual_limit,
                "claims_used": claims_used,
                "network_tier": 1 + ((i - 1) % 3),
                "policy_blob_prefix": f"policy-docs/{mid}/",
                "security_question_1": "What city were you born in?",
                "security_answer_1": city,
                "security_question_2": "What is your mother's maiden name?",
                "security_answer_2": maiden,
            }
        )
    return rows


def _print_data_explorer_hint() -> None:
    dbn = _database_id()
    cn = settings.cosmos_container
    print()
    print("Cosmos layout (NoSQL API): policyholders is a CONTAINER inside a DATABASE (not a database name).")
    print(f"  Account: host from COSMOS_DB_ENDPOINT (e.g. *.documents.azure.com)")
    print(f"  Database id: {dbn!r}  (COSMOS_DB_DATABASE / COSMOS_DATABASE)")
    print(f"  Container id: {cn!r}  (COSMOS_CONTAINER)")
    print("  Partition key for this container: /member_id")
    print()
    print("Azure Portal > your Cosmos account > Data Explorer > expand the database above > open the container.")
    print("If the container is missing, a successful seed creates it, or create it manually with partition /member_id.")


if __name__ == "__main__":
    records = build_synthetic_policyholders(20)
    if db._container is None:
        print("Could not open Cosmos - no policyholders container was created or reached.")
        if PolicyholderDB.last_init_error:
            print(f"Reason: {PolicyholderDB.last_init_error}")
        if PolicyholderDB.last_init_error and "Unauthorized" in PolicyholderDB.last_init_error:
            print(
                "Fix: In Portal > Keys, copy the primary/secondary key for THIS account "
                "into COSMOS_DB_KEY (must match COSMOS_DB_ENDPOINT)."
            )
        _print_data_explorer_hint()
        print("Sample rows (not written):")
        for p in records[:3]:
            print(f"  {p['member_id']}: {p['name']} | {p['email']} | {p['phone']}")
        print(f"  ... ({len(records)} total)")
    else:
        for record in records:
            result = db.upsert_policyholder(record)
            print(f"Seeded: {result.get('member_id')} - {result.get('name')}")
        print(f"\nSeeded {len(records)} policyholders into Cosmos DB.")
        _print_data_explorer_hint()
