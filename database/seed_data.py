"""
database/seed_data.py
Seeds 5 sample policyholders into Cosmos DB.
Run: python database/seed_data.py
"""
import sys
import os

# Add project root to sys.path
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from database.cosmos_client import db

SAMPLE_POLICYHOLDERS = [
    {
        "id": "POL-001",
        "policy_id": "POL-001",
        "name": "Sarah O'Brien",
        "dob": "1985-03-14",
        "plan_name": "PremiumCare Plus",
        "plan_type": "comprehensive",
        "deductible": 500,
        "deductible_used": 200,
        "annual_limit": 100000,
        "claims_used": 12500,
        "network_tier": 1,
        "phone": "+353-87-111-2233",
    },
    {
        "id": "POL-002",
        "policy_id": "POL-002",
        "name": "James Murphy",
        "dob": "1972-07-22",
        "plan_name": "StandardCare",
        "plan_type": "standard",
        "deductible": 1000,
        "deductible_used": 800,
        "annual_limit": 50000,
        "claims_used": 7800,
        "network_tier": 2,
        "phone": "+353-85-222-3344",
    },
    {
        "id": "POL-003",
        "policy_id": "POL-003",
        "name": "Aoife Kelly",
        "dob": "1990-11-05",
        "plan_name": "BasicCare",
        "plan_type": "basic",
        "deductible": 2000,
        "deductible_used": 0,
        "annual_limit": 25000,
        "claims_used": 1200,
        "network_tier": 3,
        "phone": "+353-86-333-4455",
    },
    {
        "id": "POL-004",
        "policy_id": "POL-004",
        "name": "Ciarán Walsh",
        "dob": "1965-02-28",
        "plan_name": "SeniorCare Gold",
        "plan_type": "senior",
        "deductible": 250,
        "deductible_used": 250,
        "annual_limit": 150000,
        "claims_used": 45000,
        "network_tier": 1,
        "phone": "+353-83-444-5566",
    },
    {
        "id": "POL-005",
        "policy_id": "POL-005",
        "name": "Niamh Brennan",
        "dob": "2000-08-19",
        "plan_name": "YoungAdult Starter",
        "plan_type": "basic",
        "deductible": 1500,
        "deductible_used": 0,
        "annual_limit": 20000,
        "claims_used": 0,
        "network_tier": 3,
        "phone": "+353-89-555-6677",
    },
]

if __name__ == "__main__":
    if db._container is None:
        print("Cosmos DB not configured — printing sample data only:")
        for p in SAMPLE_POLICYHOLDERS:
            print(f"  {p['policy_id']}: {p['name']} / {p['plan_name']}")
    else:
        for record in SAMPLE_POLICYHOLDERS:
            result = db.upsert_policyholder(record)
            print(f"Seeded: {result['policy_id']} - {result['name']}")
        print(f"\nSeeded {len(SAMPLE_POLICYHOLDERS)} policyholders into Cosmos DB.")
