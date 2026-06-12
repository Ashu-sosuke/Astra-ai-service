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
res = supabase.table("incidents").select("id, status, final_severity, fusion_score, threat_type, latitude, longitude, created_at, services_needed").order("created_at", desc=True).execute()

print(f"Total incidents: {len(res.data)}")
for idx, row in enumerate(res.data):
    print(f"#{idx+1}: ID={row.get('id')} Created={row.get('created_at')} Status={row.get('status')} Services={row.get('services_needed')}")
    print(f"    Threat={row.get('threat_type')} Sev={row.get('final_severity')} Lat={row.get('latitude')} Lng={row.get('longitude')}")
