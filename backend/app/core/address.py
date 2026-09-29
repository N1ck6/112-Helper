"""Приведение адреса к сопоставимому виду.

Оператор записывает адрес так, как привык или как сказал заявитель: «ул. Академика Королёва»,
«Академика Королёва», «Центральный административный округ», «д. 3». В эталоне то же самое
может быть записано иначе: «улица Академика Королёва», «ЦАО», «3». Для оценки важно, указан ли
тот же адрес, а не то же написание, поэтому сравниваются канонические формы.
"""

from __future__ import annotations

import re

OKRUGS: dict[str, tuple[str, ...]] = {
    "цао": ("центральный",),
    "сао": ("северный",),
    "свао": ("северо восточный", "северовосточный"),
    "вао": ("восточный",),
    "ювао": ("юго восточный", "юговосточный"),
    "юао": ("южный",),
    "юзао": ("юго западный", "югозападный"),
    "зао": ("западный",),
    "сзао": ("северо западный", "северозападный"),
    "зелао": ("зеленоградский",),
    "нао": ("новомосковский",),
    "тао": ("троицкий",),
}

_OKRUG_WORDS = ("административный", "адм", "округ", "ао", "г", "города", "москвы", "москва")

STREET_TYPES: dict[str, str] = {
    "улица": "улица", "ул": "улица",
    "проспект": "проспект", "пр-т": "проспект", "просп": "проспект", "пр-кт": "проспект",
    "переулок": "переулок", "пер": "переулок",
    "бульвар": "бульвар", "б-р": "бульвар", "бул": "бульвар",
    "шоссе": "шоссе", "ш": "шоссе",
    "площадь": "площадь", "пл": "площадь",
    "набережная": "набережная", "наб": "набережная",
    "проезд": "проезд", "пр-д": "проезд",
    "тупик": "тупик", "туп": "тупик",
    "аллея": "аллея", "ал": "аллея",
    "линия": "линия", "лин": "линия",
    "квартал": "квартал", "кв-л": "квартал",
    "микрорайон": "микрорайон", "мкр": "микрорайон", "мкрн": "микрорайон",
    "тракт": "тракт",
    "просека": "просека",
}

_AREA_WORDS = ("район", "р-н", "рн", "поселение", "пос", "муниципальный", "округ", "мо")
_REGION_WORDS = ("г", "город", "гор")
_HOUSE_WORDS = ("д", "дом", "вл", "влд", "владение")
_BUILDING_MAP = {"к": "к", "корп": "к", "корпус": "к", "с": "с", "стр": "с", "строение": "с"}
_FLAT_WORDS = ("кв", "квартира", "оф", "офис", "пом", "помещение")
_ENTRANCE_WORDS = ("п", "под", "подъезд", "подьезд")
_FLOOR_WORDS = ("эт", "этаж")


def _tokens(value: object) -> list[str]:
    """Слова в нижнем регистре; дефис внутри сокращений вида «пр-т», «р-н» сохраняется."""
    text = str(value or "").lower().replace("ё", "е")
    text = re.sub(r"(?<=[а-яa-z])-(?=[а-яa-z])", "-", text)
    text = re.sub(r"[^\w\s-]", " ", text)
    text = re.sub(r"(?<=\d)(?=[а-яa-z])|(?<=[а-яa-z])(?=\d)", " ", text)
    return [token.strip("-") for token in text.split() if token.strip("-")]


def _drop(tokens: list[str], words: tuple[str, ...]) -> list[str]:
    return [token for token in tokens if token not in words]


def okrug(value: object) -> str:
    """Административный округ Москвы → аббревиатура («Центральный АО» → «цао»)."""
    tokens = _tokens(value)
    if not tokens:
        return ""
    for token in tokens:
        if token in OKRUGS:
            return token
    rest = " ".join(_drop([t.replace("-", " ") for t in tokens], _OKRUG_WORDS))
    for code, names in OKRUGS.items():
        if rest in names:
            return code
    return rest


def street(value: object) -> tuple[str | None, str]:
    """Улица → (тип улицы или None, название без типа, слова по алфавиту)."""
    kind: str | None = None
    words: list[str] = []
    for token in _tokens(value):
        if token in STREET_TYPES and kind is None:
            kind = STREET_TYPES[token]
            continue
        words.append(token.replace("-", " "))
    return kind, " ".join(sorted(" ".join(words).split()))


def _plain(value: object, words: tuple[str, ...]) -> str:
    return "".join(_drop(_tokens(value), words))


def house(value: object) -> str:
    """Дом: «д. 3», «дом 3», «3» → «3»; «д. 12 корп. 1» → «12к1»."""
    parts: list[str] = []
    for token in _drop(_tokens(value), _HOUSE_WORDS):
        parts.append(_BUILDING_MAP.get(token, token))
    return "".join(parts)


def building(value: object) -> str:
    return "".join(_BUILDING_MAP.get(token, token) for token in _tokens(value))


def area(value: object) -> str:
    return " ".join(t.replace("-", " ") for t in _drop(_tokens(value), _AREA_WORDS))


def region(value: object) -> str:
    return " ".join(_drop(_tokens(value), _REGION_WORDS))


def same(field: str, actual: object, expected: object) -> bool:
    """Совпадает ли по смыслу значение поля адреса с эталоном."""
    if field == "address_street":
        kind_a, name_a = street(actual)
        kind_e, name_e = street(expected)
        if not name_a or name_a != name_e:
            return False
        return kind_a is None or kind_e is None or kind_a == kind_e
    normalizer = {
        "address_district": okrug,
        "address_area": area,
        "address_region": region,
        "address_house": house,
        "address_building": building,
        "address_flat": lambda v: _plain(v, _FLAT_WORDS),
        "address_entrance": lambda v: _plain(v, _ENTRANCE_WORDS),
        "address_floor": lambda v: _plain(v, _FLOOR_WORDS),
    }.get(field)
    if normalizer is None:
        return " ".join(_tokens(actual)) == " ".join(_tokens(expected))
    left = normalizer(actual)
    return bool(left) and left == normalizer(expected)
