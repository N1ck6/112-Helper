import json
from pathlib import Path
from collections import Counter

BASE_DIR = Path(__file__).resolve().parent
INPUT_PATH = BASE_DIR / "data" / "processed" / "classified_tickets.json"


def load_json(path):
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)


def get_tickets(data):
    if isinstance(data, list):
        return data

    if isinstance(data, dict):
        for key in ("tickets", "билеты", "items", "data"):
            if isinstance(data.get(key), list):
                return data[key]

    raise ValueError("Не найден список билетов")


def get_situations(ticket):
    for key in ("situations", "ситуации", "incidents", "cases"):
        value = ticket.get(key)
        if isinstance(value, list):
            return value
    return []


def get_description(situation):
    if isinstance(situation, str):
        return situation

    for key in ("description", "Описание", "text", "текст", "situation"):
        if situation.get(key):
            return str(situation[key])

    return str(situation)


def get_code(incident):
    if not isinstance(incident, dict):
        return "?"

    return str(
        incident.get("number")
        or incident.get("code")
        or incident.get("id")
        or "?"
    )


def get_name(incident):
    if not isinstance(incident, dict):
        return str(incident)

    return (
        incident.get("incident_type")
        or incident.get("ekp35_type")
        or incident.get("group")
        or incident.get("category")
        or "Без названия"
    )


def main():
    data = load_json(INPUT_PATH)
    tickets = get_tickets(data)

    statuses = Counter()
    total = 0

    print("=" * 100)
    print("ДИАГНОСТИКА СОПОСТАВЛЕНИЯ")
    print("=" * 100)

    for ticket_index, ticket in enumerate(tickets, start=1):
        situations = get_situations(ticket)

        for situation_index, situation in enumerate(situations, start=1):
            total += 1

            description = get_description(situation)
            result = situation.get("classification", {})
            status = result.get("status", "unknown")
            statuses[status] += 1

            code = result.get("best_match_code", "?")
            name = result.get("best_match_name", "?")
            score = result.get("score", "?")
            margin = result.get("margin", "?")
            events = result.get("event_types", [])

            print()
            print("-" * 100)
            print(f"Билет {ticket_index} / ситуация {situation_index}")
            print(f"Описание: {description}")
            print(f"События: {events}")
            print(f"Статус: {status} | Score: {score} | Margin: {margin}")
            print(f"Выбрано: {code} | {name}")

            alternatives = result.get("alternatives", [])

            if alternatives:
                print("Альтернативы:")

                for alternative in alternatives[:3]:
                    if isinstance(alternative, dict):
                        incident = alternative.get("incident", {})
                        alt_score = alternative.get("score", "?")
                        print(
                            f"  {get_code(incident)} | "
                            f"{get_name(incident)} | score={alt_score}"
                        )

    print()
    print("=" * 100)
    print(f"Всего ситуаций: {total}")
    print("Статистика:", dict(statuses))
    print("=" * 100)


if __name__ == "__main__":
    main()
