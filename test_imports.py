
import sys
import os

# Add the current directory to sys.path
sys.path.append(os.getcwd())

try:
    print("Testing import of database.cosmos_client...")
    from database.cosmos_client import db
    print("Import successful. db._container is:", db._container)
    if db.last_init_error:
        print("Last init error:", db.last_init_error)
except Exception as e:
    print("Failed to import database.cosmos_client:", e)
    import traceback
    traceback.print_exc()

try:
    print("\nTesting import of database.seed_data...")
    from database.seed_data import build_synthetic_policyholders
    print("Import successful. Building synthetic policyholders...")
    items = build_synthetic_policyholders(2)
    print("Built", len(items), "items.")
except Exception as e:
    print("Failed to import/run database.seed_data:", e)
    import traceback
    traceback.print_exc()
