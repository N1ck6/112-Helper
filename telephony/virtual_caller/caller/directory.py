"""Справочник служб и собеседники (persona) учебных звонков.

Persona — кто говорит «с той стороны»: имя, должность, служба, пол (голос).
Источник — directory.json; позже справочник может приходить от Backend
(тот же формат через DIRECTORY_PATH).
"""

import json
import zlib
from pathlib import Path

# Типы учебных звонков
DISPATCH = "dispatch"          # диспетчер ДДС -> служба (руководитель/дежурный)
REPORT = "report"              # старший группы -> диспетчер ДДС (доклад об обстановке)
APPLICANT = "applicant"        # диспетчер ДДС -> заявитель (номер из карточки)
INCIDENT_112 = "incident_112"  # заявитель -> оператор 112 (голосовые вводные)
CALL_TYPES = (DISPATCH, REPORT, APPLICANT, INCIDENT_112)

APPLICANT_NUMBER = "3000"      # набор с телефона: перезвонить заявителю текущей карточки
ECHO = "echo"                  # служебные номера без собеседника (проверка звука)

# Номера, кроме служб 2XXX из directory.json (= extensions.conf, контекст training/internal).
SPECIAL_NUMBERS = [
    {"number": APPLICANT_NUMBER, "call_type": APPLICANT, "title": "Заявитель открытой карточки"},
    {"number": "700", "call_type": INCIDENT_112, "scenario_id": "scenario_001",
     "title": "Учебный вызов 112: пожар в квартире"},
    {"number": "701", "call_type": INCIDENT_112, "scenario_id": "scenario_002",
     "title": "Учебный вызов 112: ДТП с пострадавшими"},
    {"number": "600", "call_type": ECHO, "title": "Эхо-тест: проверка микрофона и звука"},
]

# Женские имена в русском в основном оканчиваются на -а/-я (Никита/Илья — исключения).
_MALE_EXCEPTIONS = {"никита", "илья", "кузьма", "фома", "лука", "савва", "данила"}


def guess_gender(full_name: str | None, default: str = "female") -> str:
    """Пол по имени из карточки («Иван И., очевидец» -> male). Грубая эвристика для голоса."""
    if not full_name:
        return default
    first = full_name.replace(",", " ").split()[0].strip(".").lower()
    if first in _MALE_EXCEPTIONS:
        return "male"
    return "female" if first.endswith(("а", "я")) else "male"


def voice_for(persona: dict | None) -> str:
    return "male" if (persona or {}).get("gender") == "male" else "female"


def tts_voice(persona: dict | None) -> str:
    """Голос синтеза: пол + номер тембра по имени собеседника («female-37»).

    voice-service выбирает голос категории по номеру: у каждого собеседника свой тембр,
    и один и тот же человек звучит одинаково во всех звонках.
    """
    gender = voice_for(persona)
    key = (persona or {}).get("name") or (persona or {}).get("id") or ""
    return f"{gender}-{zlib.crc32(key.encode('utf-8')) % 100}" if key else gender


class Directory:
    def __init__(self, contacts: list[dict]):
        self.contacts = contacts
        self._by_number = {c["number"]: c for c in contacts}
        self._by_id = {c["id"]: c for c in contacts}

    @classmethod
    def load(cls, path: Path) -> "Directory":
        data = json.loads(Path(path).read_text(encoding="utf-8"))
        return cls(data.get("contacts", []))

    def public(self) -> list[dict]:
        """Для GET /directory: без служебного текста ответа."""
        return [{k: c.get(k) for k in ("number", "id", "service", "name", "position", "gender")}
                for c in self.contacts]

    def numbers(self) -> list[dict]:
        """Телефонная книга рабочего места (GET /numbers): службы + служебные номера."""
        services = [{"number": c["number"], "call_type": DISPATCH, "title": c["service"],
                     "name": c.get("name"), "position": c.get("position"), "gender": c.get("gender")}
                    for c in self.contacts]
        return services + [dict(n) for n in SPECIAL_NUMBERS]

    def dial_target(self, number: str) -> dict:
        """Что будет при наборе номера — для подписи звонка до ответа AGI.

        {"call_type": ..., "title": ..., "persona": ..., "handled_by_agi": bool}
        """
        contact = self._by_number.get(number)
        if contact:
            return {"call_type": DISPATCH, "title": contact["service"],
                    "persona": self.persona(contact, DISPATCH), "handled_by_agi": True}
        for n in SPECIAL_NUMBERS:
            if n["number"] == number:
                return {"call_type": n["call_type"], "title": n["title"], "persona": None,
                        "handled_by_agi": n["call_type"] != ECHO, "scenario_id": n.get("scenario_id")}
        # неизвестный номер: dialplan отдаёт его AGI, собеседник — «номер не обслуживается»
        return {"call_type": DISPATCH, "title": f"Номер {number}", "persona": None, "handled_by_agi": True}

    def resolve(self, ref: str | None) -> dict | None:
        """Номер (2101), id (mchs_101) или название службы из карточки («Служба 101 (МЧС)»)."""
        if not ref:
            return None
        ref = str(ref).strip()
        found = self._by_number.get(ref) or self._by_id.get(ref)
        if found:
            return found
        low = ref.casefold()
        for c in self.contacts:
            if c["service"].casefold() == low:
                return c
        for c in self.contacts:
            if any(a in low for a in c.get("aliases", [])):
                return c
        return None

    @staticmethod
    def persona(contact: dict, call_type: str = DISPATCH) -> dict:
        """Собеседник: для доклада — старший группы службы, иначе — её дежурный."""
        base = {"id": contact["id"], "number": contact["number"], "service": contact["service"],
                "name": contact.get("name"), "position": contact.get("position"),
                "gender": contact.get("gender", "male"), "accept": contact.get("accept")}
        if call_type == REPORT and contact.get("leader"):
            base.update({k: v for k, v in contact["leader"].items() if v})
        return base

    @staticmethod
    def applicant(card: dict | None) -> dict:
        card = card or {}
        name = card.get("caller") or card.get("applicant") or "Заявитель"
        gender = card.get("caller_gender") or guess_gender(name)
        return {"id": "applicant", "number": card.get("phone") or APPLICANT_NUMBER, "service": "Заявитель",
                "name": name, "position": "заявитель", "gender": gender}
