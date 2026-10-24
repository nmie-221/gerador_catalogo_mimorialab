from __future__ import annotations

import re
import math
from typing import Iterable


def normalize(value: object) -> str:
    return " ".join(str(value or "").split()).casefold()


def clean(value: object) -> str:
    return " ".join(str(value or "").split())


def required(value: object, label: str) -> str:
    result = clean(value)
    if not result:
        raise ValueError(f"Informe {label}.")
    return result


def required_fields(fields: dict[str, object]) -> list[str]:
    return [label for label, value in fields.items() if not clean(value)]


def unique(values: Iterable[object], candidate: object) -> bool:
    target = normalize(candidate)
    return not any(normalize(value) == target for value in values)


def abbreviation(value: object) -> str:
    result = clean(value).upper()
    if not re.fullmatch(r"[A-Z0-9]{1,4}", result):
        raise ValueError("A abreviacao deve conter de 1 a 4 letras ou numeros.")
    return result


def number(value: object, label: str, minimum: float = 0) -> float:
    try:
        if isinstance(value, str):
            value = value.strip()
            if "," in value:
                value = value.replace(".", "").replace(",", ".")
        result = float(value)
    except (TypeError, ValueError) as exc:
        raise ValueError(f"{label} deve ser numerico.") from exc
    if not math.isfinite(result):
        raise ValueError(f"{label} deve ser um numero finito.")
    if result < minimum:
        raise ValueError(f"{label} nao pode ser negativo.")
    return result
