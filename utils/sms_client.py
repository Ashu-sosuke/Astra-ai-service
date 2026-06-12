import logging
from twilio.rest import Client
from twilio.base.exceptions import TwilioRestException
from config import config

logger = logging.getLogger("sms_client")

class SMSClient:
    def __init__(self):
        self.enabled = all([config.TWILIO_ACCOUNT_SID, config.TWILIO_AUTH_TOKEN, config.TWILIO_FROM_NUMBER])
        if self.enabled:
            try:
                self.client = Client(config.TWILIO_ACCOUNT_SID, config.TWILIO_AUTH_TOKEN)
                logger.info("Twilio SMS Client initialized successfully.")
            except Exception as e:
                logger.error(f"Failed to initialize Twilio client: {e}")
                self.enabled = False
        else:
            logger.warning("Twilio credentials missing. SMS alerts will be disabled.")

    def send_sms(self, to_phone: str, message: str):
        if not self.enabled:
            logger.warning(f"SMS skipped (Twilio disabled): To={to_phone}")
            return False

        try:
            # Clean and normalize phone number
            cleaned = "".join(c for c in to_phone if c.isdigit() or c == "+")
            if not cleaned.startswith("+"):
                if cleaned.startswith("0"):
                    cleaned = cleaned[1:]
                
                # Check if it has 10 digits (Standard Indian phone number)
                if len(cleaned) == 10:
                    cleaned = "+91" + cleaned
                # Check if it has 12 digits and starts with 91 (India country code already there)
                elif cleaned.startswith("91") and len(cleaned) == 12:
                    cleaned = "+" + cleaned
                else:
                    cleaned = "+91" + cleaned
            
            logger.info(f"Normalized destination phone number: {to_phone} -> {cleaned}")
            to_phone = cleaned

            msg_res = self.client.messages.create(
                body=message,
                from_=config.TWILIO_FROM_NUMBER,
                to=to_phone
            )
            logger.info(f"SMS sent successfully to {to_phone}. SID: {msg_res.sid}")
            return True
        except TwilioRestException as e:
            if e.code == 21608:
                logger.error(
                    f"❌ Twilio Trial Account limit: The number {to_phone} is unverified. "
                    "Trial accounts cannot send messages to unverified numbers.\n"
                    "👉 To fix this:\n"
                    "   1. Go to twilio.com/user/account/phone-numbers/verified and verify this number, OR\n"
                    "   2. Upgrade your Twilio account from Trial to Paid."
                )
            else:
                logger.error(f"Failed to send SMS to {to_phone} (Twilio Error {e.code}): {e.msg}")
            return False
        except Exception as e:
            logger.error(f"Failed to send SMS to {to_phone}: {e}")
            return False

sms_client = SMSClient()

