import logging
from utils.sms_client import sms_client

# Configure logging to see output
logging.basicConfig(level=logging.INFO)

def test_sms():
    # REPLACE THIS with your verified phone number (e.g., '+919876543210')
    target_number = "+919631945501" 
    
    print(f"🚀 Sending test SOS alert to {target_number}...")
    success = sms_client.send_sms(
        target_number, 
        "🚨 AstraSOS Cloud SMS Test: Setup Successful! Your trusted contacts will receive this during an emergency."
    )
    
    if success:
        print("✅ SUCCESS: Test SMS sent. Check your phone!")
    else:
        print("❌ FAILED: Check your Twilio credentials in .env and ensure the number is verified.")

if __name__ == "__main__":
    test_sms()
