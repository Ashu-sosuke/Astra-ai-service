import base64
from Crypto.Cipher import AES
from Crypto.Util.Padding import unpad

class CryptoManager:
    SECRET = "MY_SUPER_SECRET_32_BYTE_KEY"

    @classmethod
    def get_key(cls):
        return cls.SECRET.encode().ljust(32, b'\0')[:32]

    @classmethod
    def decrypt(cls, encrypted_text: str):
        try:
            key = cls.get_key()
            decoded = base64.b64decode(encrypted_text)
            cipher = AES.new(key, AES.MODE_ECB)
            decrypted = cipher.decrypt(decoded)
            
            # Remove PKCS7 padding
            try:
                return unpad(decrypted, AES.block_size).decode('utf-8')
            except ValueError:
                # If unpadding fails, it might not be padded or use a different scheme
                return decrypted.decode('utf-8', errors='ignore').strip()
        except Exception as e:
            print(f"Decryption failed: {e}")
            return None

# For testing
if __name__ == "__main__":
    # If the Java code used "AES" it defaults to ECB in many Android versions if no provider specified.
    # We might need to adjust this if the Java side is actually using CBC.
    pass
