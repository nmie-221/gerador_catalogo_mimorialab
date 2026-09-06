from __future__ import annotations


def ean13_checksum(first_twelve: str) -> str:
    if len(first_twelve) != 12 or not first_twelve.isdigit():
        raise ValueError("A base do EAN-13 deve conter 12 numeros.")
    total = sum(int(value) * (1 if index % 2 == 0 else 3) for index, value in enumerate(first_twelve))
    return str((10 - total % 10) % 10)


def generate_ean13(product_id: str) -> str:
    digits = "".join(character for character in str(product_id) if character.isdigit())
    if not digits:
        raise ValueError("Nao foi possivel gerar o EAN-13 a partir do ID do produto.")
    return f"{int(digits):012d}" + ean13_checksum(f"{int(digits):012d}")


def validate_ean13(value: str) -> str:
    digits = "".join(character for character in str(value).strip() if character.isdigit())
    if len(digits) != 13 or ean13_checksum(digits[:12]) != digits[-1]:
        raise ValueError("O codigo de barras deve ser um EAN-13 valido com 13 numeros.")
    return digits
