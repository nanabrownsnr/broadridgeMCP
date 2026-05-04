from hashlib import sha256


def get_sha256(value: str) -> str:
    return sha256(value.encode("utf-8")).hexdigest()
