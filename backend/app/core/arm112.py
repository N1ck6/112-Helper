from __future__ import annotations

from typing import Any

from app.models.enums import ResponseStatus

CARD_FIELD_GROUPS: list[dict[str, Any]] = [
    {"code": "card_info", "label": "Информация о карточке", "order": 1, "readonly": True},
    {"code": "phones", "label": "Телефоны", "order": 2},
    {"code": "applicant", "label": "Заявитель", "order": 3},
    {"code": "address", "label": "Адрес", "order": 4},
    {"code": "incident", "label": "Что случилось", "order": 5},
    {"code": "flags", "label": "Признаки и метки", "order": 6},
    {"code": "description", "label": "Описание", "order": 7},
    {"code": "processing", "label": "Отработка и оповещение", "order": 8},
]

#: Статус заявителя — памятка требует различать участника, очевидца и родственника.
APPLICANT_ROLES = ["участник", "очевидец", "родственник", "должностное лицо", "иное"]

#: Метки карточки: чрезвычайная ситуация / чрезвычайное происшествие.
EMERGENCY_MARKS = ["нет", "ЧС", "ЧП"]

DEFAULT_TEMPLATE_FIELDS: list[dict[str, Any]] = [
    # --- информация о карточке (заполняется системой)
    {"code": "card_no", "label": "Номер карточки в системе-112", "type": "string",
     "group": "card_info", "order": 1, "required": False, "readonly": True},
    {"code": "registered_at", "label": "Дата и время сохранения", "type": "datetime",
     "group": "card_info", "order": 2, "required": False, "readonly": True},
    {"code": "registered_by", "label": "Зарегистрировал (специалист-112)", "type": "string",
     "group": "card_info", "order": 3, "required": False, "readonly": True},
    {"code": "operator_no", "label": "Номер оператора Службы 112", "type": "string",
     "group": "card_info", "order": 4, "required": False, "readonly": True},
    {"code": "workstation_no", "label": "Номер АРМ Службы 112", "type": "string",
     "group": "card_info", "order": 5, "required": False, "readonly": True},
    # --- телефоны
    {"code": "aon_phone", "label": "Телефон АОН", "type": "phone", "group": "phones",
     "order": 6, "required": True, "hint": "Определяется автоматически при приёме вызова"},
    {"code": "provided_phone", "label": "Предоставленный телефон", "type": "phone",
     "group": "phones", "order": 7, "required": False, "hint": "Номер, названный заявителем"},
    {"code": "site_phone", "label": "Телефон на место", "type": "phone", "group": "phones",
     "order": 8, "required": False, "hint": "Если заявитель не на месте происшествия"},
    # --- заявитель
    {"code": "applicant_name", "label": "ФИО заявителя", "type": "string",
     "group": "applicant", "order": 9, "required": True},
    {"code": "applicant_role", "label": "Статус заявителя", "type": "select",
     "group": "applicant", "order": 10, "required": True, "options": APPLICANT_ROLES},
    # --- адрес (формализуется по базе Яндекс)
    {"code": "address_region", "label": "Субъект РФ / город", "type": "string",
     "group": "address", "order": 11, "required": True, "default": "г. Москва"},
    {"code": "address_district", "label": "Административный округ", "type": "string",
     "group": "address", "order": 12, "required": True},
    {"code": "address_area", "label": "Район", "type": "string",
     "group": "address", "order": 13, "required": False},
    {"code": "address_street", "label": "Улица", "type": "string",
     "group": "address", "order": 14, "required": True},
    {"code": "address_house", "label": "Дом / владение", "type": "string",
     "group": "address", "order": 15, "required": True},
    {"code": "address_building", "label": "Корпус / строение", "type": "string",
     "group": "address", "order": 16, "required": False},
    {"code": "address_flat", "label": "Квартира / офис", "type": "string",
     "group": "address", "order": 17, "required": False},
    {"code": "address_entrance", "label": "Подъезд", "type": "string",
     "group": "address", "order": 18, "required": False},
    {"code": "address_floor", "label": "Этаж", "type": "string",
     "group": "address", "order": 19, "required": False},
    {"code": "address_code", "label": "Код входа", "type": "string",
     "group": "address", "order": 20, "required": False},
    {"code": "address_text", "label": "Описательный адрес", "type": "text",
     "group": "address", "order": 21, "required": False,
     "hint": "Ориентиры, если адрес не формализуется; фактическое место может отличаться от "
             "зарегистрированного"},
    {"code": "address_coords", "label": "Координаты (широта, долгота)", "type": "string",
     "group": "address", "order": 22, "required": False},
    # --- что случилось
    {"code": "survey_signs", "label": "Типовые признаки происшествия (опросная карта)",
     "type": "multiselect", "group": "incident", "order": 23, "required": True},
    {"code": "incident_class", "label": "Класс происшествия", "type": "select",
     "group": "incident", "order": 24, "required": True},
    {"code": "vis_class", "label": "[ВИС] Класс", "type": "select",
     "group": "incident", "order": 25, "required": False,
     "hint": "Тип происшествия, присвоенный ведомственной информационной системой"},
    # --- признаки и метки
    {"code": "has_victims", "label": "Пострадавшие", "type": "boolean",
     "group": "flags", "order": 26, "required": False},
    {"code": "victims_count", "label": "Количество пострадавших", "type": "integer",
     "group": "flags", "order": 27, "required": False},
    {"code": "ambulance_refusal", "label": "Отказ от скорой", "type": "boolean",
     "group": "flags", "order": 28, "required": False},
    {"code": "blocked_persons", "label": "Заблокированные", "type": "boolean",
     "group": "flags", "order": 29, "required": False},
    {"code": "emergency_mark", "label": "Метка ЧС / ЧП", "type": "select",
     "group": "flags", "order": 30, "required": False, "options": EMERGENCY_MARKS},
    # --- описание
    {"code": "description", "label": "Описание происшествия", "type": "text",
     "group": "description", "order": 31, "required": True,
     "hint": "Неформализованная информация: часто содержит детали, которых нет в признаках"},
    # --- отработка и оповещение
    {"code": "processing_lines", "label": "Строки отработки", "type": "table",
     "group": "processing", "order": 32, "required": False,
     "columns": ["кто", "куда", "телефон", "ФИО принявшего", "суть сообщения"]},
    {"code": "notification_services", "label": "Список оповещения", "type": "multiselect",
     "group": "processing", "order": 33, "required": True,
     "hint": "Формируется автоматически по ЕКП и полигонам; службу можно добавить, но не удалить"},
    {"code": "operator_message", "label": "Сообщение заявителю", "type": "text",
     "group": "processing", "order": 34, "required": False},
]

#: Поля, по которым считается полнота карточки при оценке (режим «заполнение карточки»).
REQUIRED_CARD_FIELDS: tuple[str, ...] = (
    "aon_phone",
    "applicant_name",
    "address_district",
    "address_street",
    "address_house",
    "survey_signs",
    "incident_class",
    "description",
)

#: Поля адреса — используются при сравнении с эталоном как единый блок.
ADDRESS_FIELDS: tuple[str, ...] = (
    "address_region",
    "address_district",
    "address_area",
    "address_street",
    "address_house",
    "address_building",
    "address_flat",
    "address_entrance",
    "address_floor",
)

FIELD_LABELS: dict[str, str] = {field["code"]: field["label"] for field in DEFAULT_TEMPLATE_FIELDS}


def caller_knowledge(card_title: str | None, expected: dict[str, Any] | None,
                     caller_profile: dict[str, Any] | None = None) -> dict[str, Any]:
    """Что знает виртуальный заявитель о своём происшествии (для телефонии и ML).

    Только то, что заявитель может сказать оператору: суть, адрес, пострадавшие, имя.
    Уходит собеседнику на сервере — обучающемуся в браузер эталон не попадает.
    """
    expected = expected or {}
    profile = caller_profile or {}
    victims = expected.get("victims_count") if expected.get("has_victims") else 0
    return {
        "title": card_title,
        "description": expected.get("description"),
        "address": format_address(expected) or expected.get("address_text"),
        "victims": victims,
        "applicant": expected.get("applicant_name") or profile.get("name"),
        "phone": expected.get("aon_phone") or profile.get("phone"),
    }


def format_address(payload: dict[str, Any]) -> str:
    """Собирает адрес в одну строку — для отчётов, PDF и передачи в телефонию."""
    parts = [str(payload.get(code, "")).strip() for code in ADDRESS_FIELDS]
    labels = ("", "", "", "", "д. ", "к. ", "кв. ", "подъезд ", "этаж ")
    chunks = [f"{prefix}{value}" for prefix, value in zip(labels, parts, strict=True) if value]
    return ", ".join(chunks)


SERVICE_TITLES: dict[str, str] = {
    "101": "Пожарно-спасательный гарнизон (101)",
    "102": "Полиция (102)",
    "103": "Скорая медицинская помощь (103)",
    "104": "Аварийная газовая служба (104)",
    "dps": "ДПС ГИБДД",
    "mosvodokanal": "АО «Мосводоканал»",
    "moek": "ПАО «МОЭК»",
    "zhilishnik": "ГБУ «Жилищник»",
    "mchs": "ЦУКС ГУ МЧС по г. Москве",
    "adi": "ГБУ «Автомобильные дороги»",
    "codd": "ГКУ ЦОДД",
    "ods": "ОДС ПСЦ",
    "uprava": "Управа района",
    "mosbez": "ГКУ «Мосгорбезопасность»",
}

EKP_MATRIX: dict[str, list[tuple[str, bool]]] = {
    "traffic_accident": [("dps", True), ("103", False), ("101", False)],
    "fire": [("101", True), ("103", False), ("102", False)],
    "medical": [("103", True)],
    "utilities": [("mosvodokanal", True), ("zhilishnik", False)],
    "gas": [("104", True), ("101", False), ("102", False)],
    "heating": [("moek", True), ("zhilishnik", False)],
    "public_order": [("102", True)],
}

FLAG_SERVICES: dict[str, tuple[str, str]] = {
    "has_victims": ("103", "признак «пострадавшие»"),
    "blocked_persons": ("101", "признак «заблокированные»"),
    "emergency": ("mchs", "метка ЧС/ЧП"),
}

SERVICE_FORBIDDEN_STATUSES: dict[str, set[ResponseStatus]] = {
    "103": {ResponseStatus.NOT_ACCEPTED, ResponseStatus.WORK_REFUSED},
}

COMMENT_EXAMPLES: list[str] = [
    "Информация передана в диспетчерскую …, принял …",
    "Реагирование по карточке происшествия № …",
    "Не обслуживаем территорию, в компетенции …",
    "Дубль карточки № …",
    "Направлены рабочие, наряд № …",
]


def service_title(code: str) -> str:
    return SERVICE_TITLES.get(code, code)


def build_notification_list(
    category_codes: list[str] | tuple[str, ...],
    *,
    flags: dict[str, Any] | None = None,
    extra_services: list[str] | None = None,
    catalog: dict[str, list[dict[str, Any]]] | None = None,
) -> list[dict[str, Any]]:
    flags = flags or {}
    entries: dict[str, dict[str, Any]] = {}

    def add(code: str, *, is_primary: bool, reason: str) -> None:
        existing = entries.get(code)
        if existing is None:
            entries[code] = {
                "code": code,
                "name": service_title(code),
                "is_primary": is_primary,
                "reason": reason,
            }
        elif is_primary and not existing["is_primary"]:
            existing["is_primary"] = True
            existing["reason"] = reason

    for category_code in category_codes:
        if not category_code:
            continue
        from_catalog = (catalog or {}).get(category_code)
        if from_catalog is not None:
            for item in from_catalog:
                add(
                    str(item.get("code")),
                    is_primary=bool(item.get("is_primary")),
                    reason=item.get("reason") or "ЕКП",
                )
            continue
        for code, is_primary in EKP_MATRIX.get(category_code, []):
            add(code, is_primary=is_primary, reason="ЕКП")

    for flag, (code, reason) in FLAG_SERVICES.items():
        value = flags.get(flag)
        if flag == "emergency":
            value = str(flags.get("emergency_mark") or "нет").upper() in {"ЧС", "ЧП"}
        if _is_true(value):
            add(code, is_primary=False, reason=reason)

    for code in extra_services or []:
        add(str(code), is_primary=False, reason="добавлена вручную")

    ordered = sorted(entries.values(), key=lambda item: (not item["is_primary"], item["code"]))
    return ordered


def _is_true(value: Any) -> bool:
    if isinstance(value, bool):
        return value
    if isinstance(value, int | float):
        return value > 0
    if isinstance(value, str):
        return value.strip().lower() in {"да", "true", "1", "есть", "yes"}
    return False


def primary_services(notification_list: list[dict[str, Any]]) -> list[str]:
    return [item["code"] for item in notification_list if item.get("is_primary")]


def service_codes(notification_list: list[dict[str, Any]]) -> list[str]:
    return [item["code"] for item in notification_list]
