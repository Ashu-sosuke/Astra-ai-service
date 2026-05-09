import logging
from twilio.rest import Client
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
            # Ensure phone is in E.164 format if not already
            if not to_phone.startswith('+'):
                # Default to India (+91) if no prefix, or handle as needed
                # For safety, we expect the app to provide E.164
                pass

            message = self.client.messages.create(
                body=message,
                from_=config.TWILIO_FROM_NUMBER,
                to=to_phone
            )
            logger.info(f"SMS sent successfully to {to_phone}. SID: {message.sid}")
            return True
        except Exception as e:
            logger.error(f"Failed to send SMS to {to_phone}: {e}")
            return False

sms_client = SMSClient()
