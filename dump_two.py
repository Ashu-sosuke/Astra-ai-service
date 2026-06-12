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
res = supabase.table("incidents").select("*").order("created_at", desc=True).limit(2).execute()
print(json.dumps(res.data, indent=2))
