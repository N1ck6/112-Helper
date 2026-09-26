"""Справочник служб и собеседники (persona) учебных звонков.

Persona — кто говорит «с той стороны»: имя, должность, служба, пол (голос).
Источник — directory.json; позже справочник может приходить от Backend
(тот же формат через DIRECTORY_PATH).
"""

import json
from pathlib import Path

# Типы учебных звонков
DISPATCH = "dispatch"          # диспетчер ДДС -> служба (руководитель/дежурный)
REPORT = "report"              # старший группы -> диспетчер ДДС (доклад об обстановке)
APPLICANT = "applicant"        # диспетчер ДДС -> заявитель (номер из карточки)
INCIDENT_112 = "incident_112"  # заявитель -> оператор 112 (голосовые вводные)
CALL_TYPES = (DISPATCH, REPORT, APPLICANT, INCIDENT_112)

APPLICANT_NUMBER = "3000"      # набор с телефона: перезвонить заявителю текущей карточки

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
