"""Билеты-задачи заказчика → учебные сценарии и карточки.

96 ситуаций из «Билеты-задачи.pdf» (32 билета по 3 вызова) — эталонные учебные сценарии,
которые заказчик передал для тренажёра. Каждая ситуация становится сценарием с эталоном
карточки АРМ-112 и карточкой в банке заданий.

Эталон собирается только из того, что в билете сказано явно. Адреса в билетах намеренно
«живые» — ориентиры, область, МКАД, неизвестный номер дома, — поэтому улица и дом попадают
в эталон, только если записаны однозначно; остальное сверяется по описательному адресу.
Тип происшествия и службы в билетах не указаны. Автоматическая классификация ML ошибается
(например, «горит уличное освещение» распознаётся как пожар), поэтому в эталон она не
попадает: её вариант сохраняется подсказкой для преподавателя, который может дописать
эталон при проверке сценария.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import sqlalchemy as sa
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.card import IncidentCard
from app.models.enums import CardOrigin, CardStatus, DifficultyLevel, ScenarioOrigin, ScenarioStatus
from app.models.scenario import Scenario, ScenarioReference
from app.models.user import User
from app.repositories.content import CardRepository, CategoryRepository
from app.services.cards import CardService

TICKETS_FILE = Path(__file__).resolve().parents[2] / "scripts" / "data" / "tickets.json"
TITLE_PREFIX = "Билет"
SOURCE_NAME = "Билеты-задачи.pdf"

EXPECTED_ACTIONS = ["call_accepted", "field_filled", "classified", "card_submitted"]

_STREET_TYPE = (
    r"ул\.?|улица|пр-т|просп\.?|проспект|пер\.?|переулок|б-р|бульвар|ш\.?|шоссе|наб\.?|набережная|"
    r"пр-д|проезд|пл\.?|площадь|тупик|аллея|мкр\.?|микрорайон"
)
_NAME = r"[А-ЯЁ][а-яё\-]+(?:\s+[А-ЯЁ][а-яё\-]+){0,2}"
_STREET_RE = re.compile(
    rf"(?:(?<![А-Яа-яЁё])(?i:{_STREET_TYPE})\s+{_NAME}|{_NAME}\s+(?i:{_STREET_TYPE}|вал)(?![А-Яа-яЁё]))",
)
_HOUSE_RE = re.compile(r"(?<![А-Яа-яЁё])(?:дом|д)\.?\s*(\d+[а-яА-Я]?)(?![\d])")
_BUILDING_RE = re.compile(r"(?<![А-Яа-яЁё])(?:корп|к|стр|с)\.?\s*(\d+)")
_FLAT_RE = re.compile(r"(?<![А-Яа-яЁё])кв\.?\s*(\d+)")
_ENTRANCE_RE = re.compile(r"(?<![А-Яа-яЁё])(?:под|подъезд)\.?\s*(\d+)")
_FLOOR_RE = re.compile(r"(?<![А-Яа-яЁё])эт\.?\s*(\d+)|(\d+)\s*этаж")
_PHONE_RE = re.compile(r"(?:\+?7|8)?[\s\-(]*(9\d{2})[\s\-)]*(\d{3})[\s\-]*(\d{2})[\s\-]*(\d{2})(?!\d)")
_FIO_RE = re.compile(
    r"[А-ЯЁ][а-яё]+(?:-[А-ЯЁ][а-яё]+)?\s+[А-ЯЁ][а-яё]+\s+[А-ЯЁ][а-яё]+(?:вич|вна|чна|ична|ич)\b"
)
_VICTIMS_RE = re.compile(r"(\d+)\s+пострадавш")
_NO_VICTIMS_RE = re.compile(r"пострадавш\w*\s+(?:людей\s+)?нет|без пострадавш", re.IGNORECASE)

#: Основная служба классификатора → код службы в списке оповещения АРМ-112
MAIN_SERVICE_CODES = {"MCHS": "101", "Police": "102", "AMBULANCE": "103", "MOSGAZ": "104"}

#: Раздел классификатора / основная служба → учебная категория backend
CATEGORY_BY_SECTION = {
    "Пожары и задымления": "fire",
    "Запах газа": "gas",
    "Аварии и происшествия в городском хозяйстве": "utilities",
}
CATEGORY_BY_SERVICE = {"Police": "public_order", "AMBULANCE": "medical", "MOSGAZ": "gas"}


@dataclass(slots=True)
class TicketCase:
    ticket: int
    situation: int
    description: str
    address: str
    incident_code: str | None
    incident_type: str | None
    incident_category: str | None
    classification: str | None
    alternatives: list[str]
    main_service: str | None = None

    @property
    def key(self) -> str:
        return f"{self.ticket}-{self.situation}"

    @property
    def confident(self) -> bool:
        return self.classification == "confident" and bool(self.incident_type)


def load_cases(path: Path = TICKETS_FILE) -> list[TicketCase]:
    items = json.loads(path.read_text(encoding="utf-8"))
    return [TicketCase(**item) for item in items]


def phone_of(text: str) -> str | None:
    found = list(_PHONE_RE.finditer(text))
    if not found:
        return None
    code, a, b, c = found[-1].groups()
    return f"+7 ({code}) {a}-{b}-{c}"


def applicant_of(text: str) -> str | None:
    found = _FIO_RE.findall(text)
    return found[-1] if found else None


def story_of(text: str) -> str:
    """Описание со слов заявителя — без ФИО и телефона, которые идут отдельными полями."""
    story = _PHONE_RE.sub("", text)
    name = applicant_of(text)
    if name:
        story = story.replace(name, "")
    story = re.sub(r"\s*,\s*(?=,|$)", "", story)
    story = re.sub(r"\s{2,}", " ", story).strip(" ,.")
    return story + "." if story else ""


def address_of(text: str) -> dict[str, str]:
    """Поля адреса, которые записаны в билете однозначно, и описательный адрес."""
    fields: dict[str, str] = {}
    lowered = text.lower()
    if "московская обл" in lowered or re.search(r"\bмо\b", lowered):
        pass
    elif "москва" in lowered or "зеленоград" in lowered or lowered.startswith(("ул", "мкад")):
        fields["address_region"] = "г. Москва"

    street = _STREET_RE.search(text)
    house = _HOUSE_RE.search(text, street.end()) if street else None
    if street:
        fields["address_street"] = street.group(0).strip()
    if street and house:
        fields["address_house"] = house.group(1)
        tail = text[house.end():]
        for code, pattern in (
            ("address_building", _BUILDING_RE),
            ("address_flat", _FLAT_RE),
            ("address_entrance", _ENTRANCE_RE),
            ("address_floor", _FLOOR_RE),
        ):
            found = pattern.search(tail)
            if found:
                fields[code] = next(group for group in found.groups() if group)

    fields["address_text"] = re.sub(r"^\s*(?:г\.\s*)?Москва\s*,\s*", "", text).strip()
    return fields


def victims_of(text: str) -> dict[str, Any]:
    if _NO_VICTIMS_RE.search(text):
        return {"has_victims": False, "victims_count": 0}
    count = _VICTIMS_RE.search(text)
    if count:
        return {"has_victims": True, "victims_count": int(count.group(1))}
    return {}


def services_of(case: TicketCase, victims: dict[str, Any]) -> list[str]:
    codes: list[str] = []
    main = MAIN_SERVICE_CODES.get(case.main_service or "")
    if main:
        codes.append(main)
    if victims.get("has_victims") and "103" not in codes:
        codes.append("103")
    if re.search(r"запах газа|утечк\w* газа", case.description, re.IGNORECASE) and "104" not in codes:
        codes.append("104")
    return codes


def expected_of(case: TicketCase) -> dict[str, Any]:
    expected: dict[str, Any] = {}
    phone = phone_of(case.description)
    if phone:
        expected["aon_phone"] = phone
    name = applicant_of(case.description)
    if name:
        expected["applicant_name"] = name
    expected.update(address_of(case.address))
    expected.update(victims_of(case.description))
    expected["description"] = story_of(case.description)
    return expected


def title_of(case: TicketCase) -> str:
    """Название без типа происшествия: в режиме заполнения карточки тип — это ответ."""
    subject = story_of(case.description)[:60].rstrip(" ,.")
    return f"{TITLE_PREFIX} {case.ticket}, вызов {case.situation}: {subject}"


class TicketImportService:
    """Загружает билеты заказчика в банк сценариев и карточек. Повторный запуск ничего не дублирует."""

    def __init__(self, session: AsyncSession) -> None:
        self.session = session
        self.cards = CardRepository(session)
        self.categories = CategoryRepository(session)
        self.card_service = CardService(session)

    async def imported_keys(self) -> set[str]:
        rows = await self.session.execute(
            sa.select(Scenario.ml_payload).where(Scenario.title.like(f"{TITLE_PREFIX} %"))
        )
        keys: set[str] = set()
        for (payload,) in rows:
            key = ((payload or {}).get("ticket") or {}).get("key")
            if key:
                keys.add(key)
        return keys

    async def import_all(self, author: User, cases: list[TicketCase] | None = None) -> dict[str, int]:
        cases = cases if cases is not None else load_cases()
        done = await self.imported_keys()
        template = await self.card_service.ensure_default_template()
        imported = 0
        for case in cases:
            if case.key in done:
                continue
            await self._import_one(case, author, template_id=template.id if template else None)
            imported += 1
        await self.session.flush()
        return {"imported": imported, "skipped": len(done)}

    async def _category_id(self, case: TicketCase, expected: dict[str, Any]):
        if not case.confident:
            return None
        code = CATEGORY_BY_SECTION.get(case.incident_category or "")
        if case.incident_category == "ДТП":
            code = "traffic_injured" if expected.get("has_victims") else "traffic_accident"
        code = code or CATEGORY_BY_SERVICE.get(case.main_service or "")
        if not code:
            return None
        category = await self.categories.by_code(code)
        return category.id if category else None

    async def _import_one(self, case: TicketCase, author: User, *, template_id) -> None:
        expected = expected_of(case)
        category_id = await self._category_id(case, expected)
        messy_address = "address_street" not in expected
        difficulty = DifficultyLevel.MEDIUM if messy_address else DifficultyLevel.BASIC
        caller = {"name": expected.get("applicant_name"), "phone": expected.get("aon_phone")}
        variants = ", ".join(v for v in [case.incident_type, *case.alternatives] if v)
        suggestion = {
            "incident_type": case.incident_type,
            "incident_code": case.incident_code,
            "services": services_of(case, victims_of(case.description)),
            "confidence": case.classification,
            "note": (
                "Тип происшествия и службы в билете не указаны; вариант ML — подсказка, "
                f"проверьте перед добавлением в эталон. Варианты: {variants or 'нет'}"
            ),
        }
        scenario = Scenario(
            title=title_of(case),
            description=case.description,
            category_id=category_id,
            difficulty=difficulty,
            status=ScenarioStatus.APPROVED,
            origin=ScenarioOrigin.MANUAL,
            author_id=author.id,
            briefing={
                "caller": caller,
                "dialogue": [
                    {"role": "caller", "text": expected["description"]},
                    {"role": "caller", "text": f"Адрес: {case.address}"},
                ],
                "address": case.address,
                "source": f"{SOURCE_NAME}, билет {case.ticket}, вызов {case.situation}",
                "ml_suggestion": suggestion,
            },
            ml_payload={
                "ticket": {
                    "key": case.key,
                    "ticket": case.ticket,
                    "situation": case.situation,
                    "incident_code": case.incident_code,
                    "classification": case.classification,
                    "alternatives": case.alternatives,
                }
            },
        )
        scenario.references.append(
            ScenarioReference(
                expected_fields=expected,
                expected_actions=EXPECTED_ACTIONS,
                expected_text={"min_length": 20},
            )
        )
        self.session.add(scenario)
        await self.session.flush()

        card = IncidentCard(
            card_no=await self.cards.next_card_no(),
            title=scenario.title,
            template_id=template_id,
            scenario_id=scenario.id,
            category_id=category_id,
            origin=CardOrigin.MANUAL,
            status=CardStatus.READY,
            difficulty=difficulty,
            caller_profile=caller,
            payload={},
            expected_payload=expected,
            incident_type_code=case.incident_code if case.confident else None,
            notification_list=await self.card_service.notification_list(
                category_id,
                expected,
                incident_type_code=case.incident_code if case.confident else None,
            ),
            time_limit_seconds=scenario.time_limit_seconds,
        )
        self.session.add(card)
        await self.session.flush()
        scenario.references[0].card_id = card.id
