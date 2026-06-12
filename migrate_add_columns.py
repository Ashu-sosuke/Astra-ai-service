"""
One-time migration: Add missing columns to the live incidents table.
Run with: python migrate_add_columns.py
"""
import os
import sys

# Fix Windows encoding
sys.stdout.reconfigure(encoding='utf-8', errors='replace')

from dotenv import load_dotenv
from supabase import create_client

load_dotenv()

url = os.getenv("SUPABASE_URL")
key = os.getenv("SUPABASE_KEY")

if not url or not key:
    print("[FAIL] SUPABASE_URL or SUPABASE_KEY not set in .env")
    exit(1)

client = create_client(url, key)

alter_statements = [
    "ALTER TABLE public.incidents ADD COLUMN IF NOT EXISTS services_needed JSONB DEFAULT '[]'::jsonb;",
    "ALTER TABLE public.incidents ADD COLUMN IF NOT EXISTS secondary_threats JSONB DEFAULT '[]'::jsonb;",
    "ALTER TABLE public.incidents ADD COLUMN IF NOT EXISTS situation_details TEXT;",
    "ALTER TABLE public.incidents ADD COLUMN IF NOT EXISTS victim_count INTEGER DEFAULT 0;",
]

print("[INFO] Adding missing columns to incidents table...")
for sql in alter_statements:
    try:
        res = client.postgrest.rpc("exec_sql", {"sql": sql}).execute()
        print(f"  [OK] {sql[:60]}...")
    except Exception as e:
        print(f"  [WARN] RPC method not available (expected): {str(e)[:80]}")

print("")
print("=== RUN THESE IN SUPABASE SQL EDITOR IF RPC FAILED ===")
for sql in alter_statements:
    print(f"  {sql}")
print("")

# Verify: try to read an incident to check if columns exist
try:
    res = client.table("incidents").select("services_needed,secondary_threats,situation_details,victim_count").limit(1).execute()
    print(f"[OK] Column verification passed. Got {len(res.data)} row(s).")
except Exception as e:
    print(f"[FAIL] Columns not yet added: {e}")
    print("[ACTION] Please run the ALTER TABLE statements above in the Supabase SQL Editor.")
