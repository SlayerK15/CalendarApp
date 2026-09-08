import hashlib
import json

from cryptography.fernet import Fernet

from app.config import settings


def digest(value: str):
    return hashlib.sha256(value.encode()).hexdigest()


def encrypt(value):
    return Fernet(settings().token_encryption_key.encode()).encrypt(json.dumps(value).encode()).decode()


def decrypt(value):
    return json.loads(Fernet(settings().token_encryption_key.encode()).decrypt(value.encode()))
