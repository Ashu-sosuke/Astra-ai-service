import os
import sys
from dotenv import load_dotenv
from supabase import create_client, Client

sys.path.append(r"d:\CodeHub\AstraSOS\ai-service")
load_dotenv(r"d:\CodeHub\AstraSOS\ai-service\.env")

url = os.getenv("SUPABASE_URL")
key = os.getenv("SUPABASE_KEY")

if not url or not key:
    print("Missing Supabase credentials in .env")
    sys.exit(1)

supabase: Client = create_client(url, key)
res = supabase.table("incidents").select("*").order("created_at", desc=True).limit(10).execute()
print(f"Retrieved {len(res.data)} incidents:")
for row in res.data:
    print(f"ID: {row.get('id')}")
    print(f"  Created At: {row.get('created_at')}")
    print(f"  Status: {row.get('status')}")
    print(f"  Threat Type: {row.get('threat_type')}")
    print(f"  Severity: {row.get('final_severity') or row.get('severity')}")
    print(f"  Services Needed: {row.get('services_needed')}")
    try:
        transcript = row.get('transcript') or row.get('transcription') or ""
        print(f"  Transcript: {transcript.encode('utf-8', errors='replace').decode('utf-8')}")
    except Exception as e:
        print(f"  Transcript (Error): {e}")
    print("-" * 40)
