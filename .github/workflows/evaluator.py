import re
from typing import Any, Dict, List, Tuple



def normalize(text: Any) -> str:
    if text is None:
        return ""
    text = str(text).lower().replace("ё", "е")
    text = re.sub(r"[^а-яa-z0-9\s-]", " ", text)
    text = re.sub(r"\s+", " ", text).strip()
    return text


def normalize_keep_punct(text: Any) -> str:
    if text is None:
        return ""
    text = str(text).lower().replace("ё", "е")
    text = re.sub(r"[^а-яa-z0-9\s?!-]", " ", text)
    text = re.sub(r"\s+", " ", text).strip()
    return text



def _has_negation_before(text: str, start: int) -> bool:
    prefix = text[max(0, start - 30):start]
    return bool(
        re.search(
            r"\b(?:не|ни|никак|никто|ничего|нет)\b",
            prefix,
            flags=re.IGNORECASE,
        )
    )


def _has_already_context(text: str, start: int) -> bool:

    prefix = text[max(0, start - 150):start]
    return bool(
        re.search(
            r"\b(?:я|мы)\s+"
            r"(?:сейчас\s+|уже\s+|потом\s+|далее\s+)?"
            r"(?:"
            r"уточню|уточним|"
            r"спрошу|спросим|"
            r"проверю|проверим|"
            r"передам|передадим|"
            r"сообщу|сообщим|"
            r"запишу|запишем|"
            r"узнаю|узнаем|"
            r"выясню|выясним"
            r")\b",
            prefix,
            flags=re.IGNORECASE,
        )
    )


def _search_patterns(text: str, patterns: List[str]) -> bool:
    for pattern in patterns:
        match = re.search(pattern, text, flags=re.IGNORECASE)
        if not match:
            continue
        if _has_negation_before(text, match.start()):
            continue
        if _has_already_context(text, match.start()):
            continue
        return True
    return False



LOCATION_ASK_PATTERNS = [
    r"\bгде\s+(?:произош\w*|случил\w*|находит\w*|находится|это)\b",
    r"\b(?:назов\w*|скаж\w*|сообщ\w*|уточн\w*|продикт\w*)\s+"
    r"(?:мне\s+)?(?:точн\w*\s+)?адрес\b",
    r"\b(?:какой|по\s+какому)\s+"
    r"(?:адрес\w*|мест\w*\s+адрес\w*)\b",
    r"\bточн\w*\s+адрес\b",
    r"\bместо\s+(?:происшеств\w*|происходящ\w*)\b",
    r"\b(?:где|по\s+какому\s+адресу)\s+"
    r"(?:это|находит\w*|произош\w*|случил\w*)",
    r"\b(?:улиц\w*|проспект\w*|переул\w*|дом\w*|квартир\w*|подъезд\w*|этаж\w*)"
    r".{0,20}\?",
]

EVENT_ASK_PATTERNS = [
    r"\bчто\s+(?:произош\w*|случил\w*|происход\w*)\b",
    r"\bчто\s+там\s+(?:произош\w*|случил\w*|происход\w*)\b",
    r"\bкакое\s+(?:происшеств\w*|событи\w*)\b",
    r"\bхарактер\s+(?:происшеств\w*|ситуаци\w*)\b",
    r"\bопиш\w*\s+(?:ситуаци\w*|происшеств\w*)\b",
    r"\bрасскаж\w*\s+(?:что\s+произош\w*|о\s+ситуаци\w*)\b",
    r"\bчто\s+произошло\b",
    r"\bчто\s+случилось\b",
]

TIME_ASK_PATTERNS = [
    r"\bкогда\s+(?:это\s+)?(?:произош\w*|случил\w*|начал\w*|возник\w*)\b",
    r"\bкогда\s+все\s+начал\w*\b",
    r"\bво\s+сколько\b",
    r"\bв\s+какое\s+время\b",
    r"\bс\s+какого\s+момента\b",
    r"\bкак\s+давно\b",
    r"\bсколько\s+времени\s+назад\b",
    r"\bточн\w*\s+время\b",
    r"\bвремя\s+(?:происшеств\w*|происходящ\w*)\b",
]


VICTIMS_ASK_PATTERNS = [
    r"\bесть\s+ли\s+(?:кто[- ]?нибудь\s+)?"
    r"(?:пострадавш\w*|ранен\w*|травмирован\w*|жертв\w*)\b",
    r"\bкто[- ]?нибудь\s+пострада\w*\b",
    r"\bкто\s+пострада\w*\b",
    r"\bсколько\s+(?:пострадавш\w*|ранен\w*|травмирован\w*)\b",
    r"\bесть\s+ли\s+люди\s+"
    r"(?:внутри|в\s+помещении|в\s+здании|в\s+машине|в\s+автомобиле)\b",
    r"\bесть\s+ли\s+кто[- ]?нибудь\s+"
    r"(?:внутри|в\s+помещении|в\s+здании|в\s+машине)\b",
    r"\bкто\s+(?:находится|находился)\s+"
    r"(?:внутри|в\s+помещении|в\s+здании|в\s+машине)\b",
]


VICTIMS_PURE_PATTERNS = [
    r"\bесть\s+ли\s+(?:кто[- ]?нибудь\s+)?"
    r"(?:пострадавш\w*|ранен\w*|травмирован\w*|жертв\w*)\b",
    r"\bкто[- ]?нибудь\s+пострада\w*\b",
    r"\bкто\s+пострада\w*\b",
    r"\bсколько\s+(?:пострадавш\w*|ранен\w*|травмирован\w*)\b",
    r"\bесть\s+ли\s+жертв\w*\b",
    r"\bпострадавш\w*\s+есть\b",
    r"\bранен\w*\s+есть\b",
]

CLARIFICATION_ASK_PATTERNS = [
    r"\bуточн\w*\s+(?:подробн\w*|дополнительн\w*|обстоятельств\w*|детал\w*|ситуаци\w*)\b",
    r"\bкакие\s+еще\s+"
    r"(?:обстоятельств\w*|детал\w*|сведени\w*)\b",
    r"\bесть\s+ли\s+еще\s+"
    r"(?:что[- ]?нибудь|обстоятельств\w*|детал\w*|сведени\w*)\b",
    r"\bесть\s+ли\s+дополнительн\w*\s+"
    r"(?:информаци\w*|сведени\w*|детал\w*)\b",
    r"\bрасскаж\w*\s+(?:подробн\w*|детальн\w*|больше)\b",
    r"\bчто[- ]?нибудь\s+еще\b",
    r"\bкакие[- ]?то\s+подробност\w*\b",
    r"\bдополнительн\w*\s+(?:вопрос\w*|информаци\w*|сведени\w*)\b",
]

HELP_ASK_PATTERNS = [
    r"\bкакая\s+(?:помощ\w*|служб\w*)\s+нужн\w*\b",
    r"\bкакую\s+служб\w*\s+вызва\w*\b",
    r"\bнужн\w*\s+(?:скор\w*\s+помощ\w*|помощ\w*)\b",
    r"\bнужн\w*\s+вызва\w*\b",
    r"\bкакая\s+служб\w*\s+нужн\w*\b",
]



FIRE_OPEN_FLAME_PATTERNS = [
    r"\bесть\s+ли\s+(?:открыт\w*\s+)?(?:огон\w*|плам\w*)\b",
    r"\bвидн\w*\s+(?:открыт\w*\s+)?(?:огон\w*|плам\w*)\b",
    r"\bесть\s+открыт\w*\s+(?:огон\w*|плам\w*)\b",
    r"\bоткрыт\w*\s+(?:огон\w*|плам\w*)\b",
]

FIRE_WHAT_BURNS_PATTERNS = [
    r"\bчто\s+именно\s+горит\b",
    r"\bчто\s+горит\b",
    r"\bчто\s+дымит\b",
    r"\bчто\s+именно\s+дымит\b",
    r"\bчто\s+загорел\w*\b",
    r"\bчто\s+горит\s+или\s+дымит\b",
]

FIRE_PEOPLE_PATTERNS = [
    r"\bесть\s+ли\s+люди\s+(?:внутри|в\s+здании|в\s+помещении)\b",
    r"\bкто[- ]?нибудь\s+(?:внутри|в\s+здании|в\s+помещении)\b",
    r"\bлюди\s+(?:внутри|в\s+здании|в\s+помещении)\b",
    r"\bкто\s+(?:находится|находился)\s+(?:внутри|в\s+здании|в\s+помещении)\b",
]

DTP_DETAILS_PATTERNS = [
    r"\bсколько\s+(?:машин|автомобил\w*|транспорт\w*)\b",
    r"\bсколько\s+(?:машин|автомобил\w*|транспорт\w*)\s+участв\w*\b",
    r"\bсколько\s+(?:участник\w*|транспортн\w*)\b",
    r"\bперекрыт\w*\s+(?:ли\s+)?дорог\w*\b",
    r"\bперекрыт\w*\s+(?:ли\s+)?движен\w*\b",
    r"\bмеша\w*\s+ли\s+(?:машин\w*|автомобил\w*|транспорт\w*)\s+движени\w*\b",
]

GAS_DETAILS_PATTERNS = [
    r"\bчувству\w*\s+ли\s+запах\s+газ\w*\b",
    r"\bесть\s+ли\s+запах\s+газ\w*\b",
    r"\bпахнет\s+ли\s+газ\w*\b",
    r"\bесть\s+ли\s+утечк\w*\b",
    r"\bгде\s+происходит\s+утечк\w*\b",
    r"\bесть\s+ли\s+люди\s+в\s+(?:опасн\w*|зон\w*)\b",
    r"\bесть\s+ли\s+люди\s+рядом\s+с\s+(?:утечк\w*|газ\w*)\b",
]

ELEVATOR_PEOPLE_PATTERNS = [
    r"\bесть\s+ли\s+люди\s+в\s+(?:кабин\w*|лифте)\b",
    r"\bнаходятся\s+ли\s+(?:люди|кто[- ]?(?:то|нибудь)|пассажир\w*)\s+в\s+(?:кабин\w*|лифте)\b",
    r"\bкто[- ]?(?:то|нибудь)\s+находится\s+в\s+(?:кабин\w*|лифте)\b",
    r"\bесть\s+ли\s+кто[- ]?(?:то|нибудь)\s+в\s+(?:кабин\w*|лифте)\b",
    r"\bсколько\s+людей\s+в\s+(?:кабин\w*|лифте)\b",
    r"\bв\s+(?:кабин\w*|лифте)\s+(?:есть\s+люди|кто[- ]?(?:то|нибудь)|находятся)\b",
]

ELEVATOR_DOORS_PATTERNS = [
    r"\bоткрыва\w*\s+ли\s+двер\w*\s+(?:лиф\w*|кабин\w*)\b",
    r"\bдвер\w*\s+(?:лиф\w*|кабин\w*)\s+открыва\w*\b",
    r"\bможно\s+ли\s+открыть\s+двер\w*\b",
    r"\bоткрыт\w*\s+ли\s+двер\w*\s+(?:лиф\w*|кабин\w*)\b",
    r"\bоткрыва\w*\s+ли\s+двер\w*\b",
]

ADDITIONAL_CIRCUMSTANCES_PATTERNS = [
    r"\bкакие\s+еще\s+(?:обстоятельств\w*|детал\w*|сведени\w*|факт\w*)\b",
    r"\bесть\s+ли\s+еще\s+(?:что[- ]?нибудь|обстоятельств\w*|детал\w*)\b",
    r"\bчто[- ]?нибудь\s+еще\b",
    r"\bчто\s+еще\s+(?:известно|знаете|можете)\b",
    r"\bкакие[- ]?то\s+подробност\w*\b",
    r"\bдополнительн\w+\s+(?:обстоятельств\w*|сведени\w*|информаци\w*|факт\w*)\b",
    r"\bкакие\s+обстоятельств\w*\b",
    r"\bрасскаж\w*\s+(?:подробн\w*|детальн\w*|больше)\b",
    r"\bуточн\w*\s+(?:подробн\w*|дополнительн\w*|детал\w*)\b",
]

ACTIONS_TAKEN_PATTERNS = [
    r"\bчто\s+(?:вы\s+)?уже\s+(?:сделал\w*|предпринял\w*|попробовал\w*)\b",
    r"\bкакие\s+действи\w*\s+(?:уже\s+)?(?:были\s+)?"
    r"(?:предпринят\w*|выполнен\w*|сделан\w*)\b",
    r"\bчто\s+уже\s+было\s+сделан\w*\b",
    r"\bкакие\s+мер\w*\s+(?:уже\s+)?(?:были\s+)?принят\w*\b",
    r"\bчто\s+предпринят\w*\b",
    r"\bчто\s+делал\w*\s+до\s+(?:этого|приезда|звонка)\b",
]


CRITERION_PATTERNS: Dict[str, List[str]] = {
    "location": LOCATION_ASK_PATTERNS,
    "event": EVENT_ASK_PATTERNS,
    "time": TIME_ASK_PATTERNS,
    "victims": VICTIMS_ASK_PATTERNS,
    "clarification": CLARIFICATION_ASK_PATTERNS,
    "help": HELP_ASK_PATTERNS,

    "fire_open_flame": FIRE_OPEN_FLAME_PATTERNS,
    "fire_what_burns": FIRE_WHAT_BURNS_PATTERNS,
    "fire_people": FIRE_PEOPLE_PATTERNS,

    "dtp_details": DTP_DETAILS_PATTERNS,
    "gas_details": GAS_DETAILS_PATTERNS,

    "elevator_people": ELEVATOR_PEOPLE_PATTERNS,
    "elevator_doors": ELEVATOR_DOORS_PATTERNS,

    "additional_circumstances": ADDITIONAL_CIRCUMSTANCES_PATTERNS,
    "actions_taken": ACTIONS_TAKEN_PATTERNS,
}


_DESC_TO_ID: Dict[str, str] = {
    "точный адрес": "location",
    "место происшествия": "location",
    "где произошло": "location",
    "что произошло": "event",
    "характер происшествия": "event",
    "когда произошло": "time",
    "время происшествия": "time",
    "пострадавшие": "victims",
    "раненые": "victims",
    "дополнительная информация": "clarification",
    "дополнительные сведения": "clarification",
    "дополнительные обстоятельства происшествия": "clarification",
    "служба": "help",

    "открытый огонь": "fire_open_flame",
    "открытое пламя": "fire_open_flame",
    "что горит": "fire_what_burns",
    "что именно горит": "fire_what_burns",
    "что именно горит или дымит": "fire_what_burns",
    "люди внутри": "fire_people",
    "люди в здании": "fire_people",

    "детали дтп": "dtp_details",
    "количество машин": "dtp_details",
    "количество участвующих транспортных средств": "dtp_details",
    "перекрытие движения": "dtp_details",

    "запах газа": "gas_details",
    "утечка газа": "gas_details",
    "опасная зона": "gas_details",

    "люди в кабине лифта": "elevator_people",
    "люди в лифте": "elevator_people",
    "двери лифта": "elevator_doors",
    "открываются ли двери лифта": "elevator_doors",

    "которые могут изменить оценку ситуации": "additional_circumstances",
    "какие действия уже были выполнены": "actions_taken",
    "действия уже были выполнены": "actions_taken",
    "что уже было сделано": "actions_taken",
    "на месте происшествия": "actions_taken",
}


def _resolve_criterion_id(criterion_id: str, description: str = "") -> str:
    raw_id = normalize(criterion_id)
    raw_description = normalize(description)

    if raw_id in CRITERION_PATTERNS:
        return raw_id

    for known_id in CRITERION_PATTERNS:
        if raw_id and known_id in raw_id:
            return known_id

    for phrase, known_id in sorted(
        _DESC_TO_ID.items(),
        key=lambda item: len(item[0]),
        reverse=True,
    ):
        if phrase in raw_description:
            return known_id

    return ""



def criterion_matches(
    answer: str,
    criterion_id: str,
    description: str = "",
    scenario_ids: set = None,
) -> Tuple[bool, str]:

    resolved_id = _resolve_criterion_id(criterion_id, description)
    if not resolved_id:
        return False, ""

    patterns = CRITERION_PATTERNS.get(resolved_id)
    if not patterns:
        return False, resolved_id

    text = normalize_keep_punct(answer)
    if not text:
        return False, resolved_id

    scenario_ids = scenario_ids or set()

    # ---- защита event ----
    if resolved_id == "event":
        if (
            "fire_what_burns" in scenario_ids
            and re.search(
                r"\bчто\s+(?:именно\s+)?(?:горит|дымит)\b",
                text,
                flags=re.IGNORECASE,
            )
        ):
            return False, resolved_id


    if resolved_id == "clarification":
        blockers: List[str] = []

        if "fire_what_burns" in scenario_ids:
            blockers += FIRE_WHAT_BURNS_PATTERNS
        if "fire_open_flame" in scenario_ids:
            blockers += FIRE_OPEN_FLAME_PATTERNS
        if "fire_people" in scenario_ids:
            blockers += FIRE_PEOPLE_PATTERNS
        if "elevator_people" in scenario_ids:
            blockers += ELEVATOR_PEOPLE_PATTERNS
        if "elevator_doors" in scenario_ids:
            blockers += ELEVATOR_DOORS_PATTERNS
        if "dtp_details" in scenario_ids:
            blockers += DTP_DETAILS_PATTERNS
        if "gas_details" in scenario_ids:
            blockers += GAS_DETAILS_PATTERNS
        if "additional_circumstances" in scenario_ids:
            blockers += ADDITIONAL_CIRCUMSTANCES_PATTERNS
        if "actions_taken" in scenario_ids:
            blockers += ACTIONS_TAKEN_PATTERNS

        if blockers and _search_patterns(text, blockers):
            return False, resolved_id


        fallback: List[str] = []
        if "elevator_people" not in scenario_ids:
            fallback += ELEVATOR_PEOPLE_PATTERNS
        if "elevator_doors" not in scenario_ids:
            fallback += ELEVATOR_DOORS_PATTERNS
        if "fire_what_burns" not in scenario_ids:
            fallback += FIRE_WHAT_BURNS_PATTERNS
        if "fire_open_flame" not in scenario_ids:
            fallback += FIRE_OPEN_FLAME_PATTERNS
        if "fire_people" not in scenario_ids:
            fallback += FIRE_PEOPLE_PATTERNS
        if "dtp_details" not in scenario_ids:
            fallback += DTP_DETAILS_PATTERNS
        if "gas_details" not in scenario_ids:
            fallback += GAS_DETAILS_PATTERNS

        if fallback and _search_patterns(text, fallback):
            return True, resolved_id

    if resolved_id == "victims":

        if _search_patterns(text, VICTIMS_PURE_PATTERNS):
            return True, resolved_id


        if "elevator_people" in scenario_ids:
            if _search_patterns(text, ELEVATOR_PEOPLE_PATTERNS):
                return False, resolved_id
        if "fire_people" in scenario_ids:
            if _search_patterns(text, FIRE_PEOPLE_PATTERNS):
                return False, resolved_id

    return _search_patterns(text, patterns), resolved_id



def get_criteria(scenario: Dict[str, Any]) -> List[Dict[str, Any]]:
    raw_criteria = scenario.get("evaluation_criteria", [])
    if not isinstance(raw_criteria, list):
        return []

    result: List[Dict[str, Any]] = []

    # [FIX] критерий "time" исключён из оценки.
    EXCLUDED_CRITERION_IDS = {"time"}

    for index, item in enumerate(raw_criteria, start=1):
        if isinstance(item, str):
            criterion_id = item
            description = item
            weight = 1.0
        elif isinstance(item, dict):
            criterion_id = (
                item.get("id")
                or item.get("criterion_id")
                or ""
            )
            description = (
                item.get("description")
                or item.get("name")
                or criterion_id
            )
            try:
                weight = float(item.get("weight", 1.0))
            except (TypeError, ValueError):
                weight = 1.0
        else:
            continue

        resolved_id = _resolve_criterion_id(
            str(criterion_id),
            str(description),
        )


        if resolved_id in EXCLUDED_CRITERION_IDS:
            continue

        result.append({
            "id": str(criterion_id),
            "resolved_id": resolved_id,
            "description": str(description),
            "weight": max(weight, 0.0),
            "index": index,
        })

    return result



_DANGEROUS_PATTERNS = [
    (
        r"\b(?:самостоятельно|самому|сама|сам)\s+"
        r"(?:войдите|заходите|входите)\s+(?:в\s+)?опасн\w*\s+зон\w*",
        "предложено самостоятельно войти в опасную зону",
    ),
    (
        r"\b(?:подойдите|подходите)\s+"
        r"(?:к\s+)?подозрительн\w*\s+предмет\w*",
        "предложено приблизиться к подозрительному предмету",
    ),
    (
        r"\b(?:возьмите|трогайте|потрогайте|поднимите)\s+"
        r"(?:подозрительн\w*\s+)?предмет\w*",
        "предложено прикоснуться к подозрительному предмету",
    ),
    (
        r"\bоткройте\s+окно\b",
        "предложено открыть окно в потенциально пожароопасной ситуации",
    ),
    (
        r"\bвключите\s+свет\b",
        "предложено включить свет при возможной утечке газа",
    ),
    (
        r"\bзажгите\s+(?:спичк\w*|зажигалк\w*)\b",
        "предложено использовать открытый огонь при возможной утечке газа",
    ),
]


def _detect_mistakes(answer: str) -> List[str]:
    text = normalize_keep_punct(answer)
    return [
        description
        for pattern, description in _DANGEROUS_PATTERNS
        if re.search(pattern, text, flags=re.IGNORECASE)
    ]




def _build_feedback(
    score: float,
    correct_actions: List[str],
    missed_actions: List[str],
    mistakes: List[str],
) -> str:
    parts: List[str] = []

    if mistakes:
        parts.append(
            "Обнаружены потенциально опасные действия: "
            + "; ".join(mistakes) + "."
        )

    if missed_actions:
        parts.append(
            "Не охвачены важные действия: "
            + "; ".join(missed_actions) + "."
        )

    if correct_actions:
        parts.append(
            "Корректно выполнено: "
            + "; ".join(correct_actions) + "."
        )

    if not correct_actions and not missed_actions and not mistakes:
        return "В ответе не удалось распознать требуемые действия оператора."

    if score >= 90:
        parts.append("Ответ практически полностью соответствует критериям.")
    elif score >= 70:
        parts.append(
            "Основные действия выполнены, но часть информации пропущена."
        )
    elif score >= 40:
        parts.append(
            "Выполнена только часть необходимых действий. "
            "Нужно уточнить недостающие сведения."
        )
    else:
        parts.append("Ответ недостаточен для полноценной обработки обращения.")

    return " ".join(parts)


def evaluate_answer(
    scenario: Dict[str, Any],
    operator_answer: str = None,
    answer: str = None,
) -> Dict[str, Any]:


    if not isinstance(scenario, dict):
        raise ValueError("scenario должен быть объектом JSON")

    text = operator_answer if operator_answer is not None else answer

    if not isinstance(text, str):
        raise ValueError("Ответ оператора должен быть строкой")

    text = text.strip()
    if not text:
        raise ValueError("Ответ оператора не может быть пустым")

    criteria = get_criteria(scenario)
    if not criteria:
        raise ValueError("В сценарии отсутствует evaluation_criteria")

    mistakes = _detect_mistakes(text)

    total_weight = 0.0
    earned_weight = 0.0
    correct_actions: List[str] = []
    missed_actions: List[str] = []
    criteria_result: List[Dict[str, Any]] = []

    scenario_ids = {
        c["resolved_id"] for c in criteria if c["resolved_id"]
    }

    for criterion in criteria:
        criterion_id = criterion["id"]
        resolved_id = criterion["resolved_id"]
        description = criterion["description"]
        weight = criterion["weight"]

        total_weight += weight

        matched, actual_resolved_id = criterion_matches(
            answer=text,
            criterion_id=criterion_id,
            description=description,
            scenario_ids=scenario_ids,
        )
        if actual_resolved_id:
            resolved_id = actual_resolved_id

        if matched:
            earned_weight += weight
            correct_actions.append(description)
        else:
            missed_actions.append(description)

        criteria_result.append({
            "id": criterion_id,
            "resolved_id": resolved_id or None,
            "description": description,
            "weight": weight,
            "matched": matched,
        })

    if total_weight > 0:
        score = (earned_weight / total_weight) * 100.0
    else:
        score = 0.0

    mistake_penalty = min(len(mistakes) * 10.0, 30.0)
    score -= mistake_penalty
    score = max(0.0, min(100.0, score))
    score = round(score, 2)

    feedback = _build_feedback(
        score=score,
        correct_actions=correct_actions,
        missed_actions=missed_actions,
        mistakes=mistakes,
    )

    classification = scenario.get("classification", {})

    unresolved = [
        c["id"] for c in criteria_result if not c["resolved_id"]
    ]

    return {
        "score": score,
        "correct_actions": correct_actions,
        "missed_actions": missed_actions,
        "mistakes": mistakes,
        "feedback": feedback,
        "criteria": criteria_result,
        "scenario_id": scenario.get("scenario_id"),
        "classification": classification,
        "debug": {
            "answer": text,
            "total_weight": total_weight,
            "earned_weight": earned_weight,
            "mistake_penalty": mistake_penalty,
            "criteria_count": len(criteria_result),
            "unresolved_criteria": unresolved,
        },
    }