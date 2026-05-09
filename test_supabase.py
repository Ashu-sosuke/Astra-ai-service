import os
import sys
from dotenv import load_dotenv
from supabase import create_client, Client

# Add current directory to path for imports
sys.path.append(os.path.dirname(os.path.abspath(__file__)))

load_dotenv()

def test_supabase_connection():
    url = os.getenv("SUPABASE_URL")
    key = os.getenv("SUPABASE_KEY")
    
    print(f"Testing connection to: {url}")
    
    if not url or not key:
        print("[FAIL] SUPABASE_URL or SUPABASE_KEY missing in .env")
        return

    try:
        supabase: Client = create_client(url, key)
        # Try to fetch from 'incidents' table
        print("Fetching from 'incidents' table...")
        res = supabase.table("incidents").select("*", count="exact").limit(1).execute()
        print(f"[PASS] Successfully connected! Table 'incidents' has {res.count} records.")
        
    except Exception as e:
        print(f"[FAIL] Connection failed: {e}")
        print("\nChecklist:")
        print("1. Is the SUPABASE_URL correct?")
        print("2. Is the SUPABASE_KEY a 'service_role' key? (needed for backend access)")
        print("3. Did you run the SQL to create the 'incidents' table?")

if __name__ == "__main__":
    test_supabase_connection()
