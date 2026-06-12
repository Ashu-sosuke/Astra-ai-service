import os
import sys
import json
from dotenv import load_dotenv
from supabase import create_client, Client

sys.path.append(r"d:\CodeHub\AstraSOS\ai-service")
load_dotenv(r"d:\CodeHub\AstraSOS\ai-service\.env")

url = os.getenv("SUPABASE_URL")
key = os.getenv("SUPABASE_KEY")

if not url or not key:
    print("Missing credentials")
    sys.exit(1)

supabase: Client = create_client(url, key)
res = supabase.table("incidents").select("*").order("created_at", desc=True).limit(5).execute()

for idx, row in enumerate(res.data):
    print(f"--- Record {idx+1} ---")
    print(json.dumps(row, indent=2))
    print("=" * 60)
