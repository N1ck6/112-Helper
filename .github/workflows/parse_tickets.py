import json
import re
from pathlib import Path


BASE_DIR = Path(__file__).resolve().parent

INPUT_FILE = BASE_DIR / "data" / "raw" / "tickets_32.txt"
OUTPUT_FILE = BASE_DIR / "data" / "processed" / "tickets.json"


def parse_tickets(text: str):


    ticket_pattern = re.compile(
        r"=+\s*TICKET\s+(\d+)\s*=+",
        re.IGNORECASE
    )

    situation_pattern = re.compile(
        r"^СИТУАЦИЯ\s+(\d+)\s*$",
        re.IGNORECASE
    )

    ticket_matches = list(ticket_pattern.finditer(text))

    if not ticket_matches:
        raise ValueError("Не найдено ни одного TICKET.")

    tickets = []

    for i, ticket_match in enumerate(ticket_matches):
        ticket_number = int(ticket_match.group(1))

        start = ticket_match.end()

        if i + 1 < len(ticket_matches):
            end = ticket_matches[i + 1].start()
        else:
            end = len(text)

        ticket_text = text[start:end].strip()

        situations = parse_situations(ticket_text)

        tickets.append({
            "ticket_id": ticket_number,
            "situations": situations
        })

    return tickets


def parse_situations(ticket_text: str):

    situation_matches = list(
        re.finditer(
            r"^СИТУАЦИЯ\s+(\d+)\s*$",
            ticket_text,
            re.MULTILINE | re.IGNORECASE
        )
    )

    situations = []

    for i, match in enumerate(situation_matches):
        situation_number = int(match.group(1))

        start = match.end()

        if i + 1 < len(situation_matches):
            end = situation_matches[i + 1].start()
        else:
            end = len(ticket_text)

        block = ticket_text[start:end].strip()

        description = extract_section(
            block,
            "Описание:",
            "Адрес:"
        )

        address = extract_section(
            block,
            "Адрес:",
            None
        )

        situations.append({
            "situation_id": situation_number,
            "description": clean_text(description),
            "address": clean_text(address)
        })

    return situations


def extract_section(text: str, start_marker: str, end_marker: str | None):


    start_index = text.find(start_marker)

    if start_index == -1:
        return ""

    start_index += len(start_marker)

    if end_marker is None:
        result = text[start_index:]
    else:
        end_index = text.find(end_marker, start_index)

        if end_index == -1:
            result = text[start_index:]
        else:
            result = text[start_index:end_index]

    return result.strip()


def clean_text(text: str):


    text = re.sub(r"[ \t]+", " ", text)
    text = re.sub(r"\n{3,}", "\n\n", text)

    return text.strip()


def validate_tickets(tickets):


    errors = []

    ticket_ids = [ticket["ticket_id"] for ticket in tickets]

    expected_ticket_ids = list(range(1, 33))

    if ticket_ids != expected_ticket_ids:
        errors.append(
            f"Номера билетов отличаются от 1–32: {ticket_ids}"
        )

    total_situations = 0

    for ticket in tickets:
        ticket_id = ticket["ticket_id"]
        situations = ticket["situations"]

        if not situations:
            errors.append(
                f"Билет {ticket_id}: нет ситуаций."
            )

        for situation in situations:
            total_situations += 1

            situation_id = situation["situation_id"]

            if not situation["description"]:
                errors.append(
                    f"Билет {ticket_id}, ситуация {situation_id}: "
                    f"пустое описание."
                )

            if not situation["address"]:
                errors.append(
                    f"Билет {ticket_id}, ситуация {situation_id}: "
                    f"пустой адрес."
                )

    if total_situations != 96:
        errors.append(
            f"Ожидалось 96 ситуаций, найдено {total_situations}."
        )

    return errors


def save_tickets(tickets):
    OUTPUT_FILE.parent.mkdir(parents=True, exist_ok=True)

    with open(
        OUTPUT_FILE,
        "w",
        encoding="utf-8"
    ) as file:
        json.dump(
            tickets,
            file,
            ensure_ascii=False,
            indent=2
        )


def print_summary(tickets):
    print()
    print("=" * 60)
    print("РЕЗУЛЬТАТ ПАРСИНГА")
    print("=" * 60)

    print(f"Билетов: {len(tickets)}")

    total_situations = sum(
        len(ticket["situations"])
        for ticket in tickets
    )

    print(f"Ситуаций: {total_situations}")

    print()
    print("Распределение ситуаций:")

    for ticket in tickets:
        print(
            f"  Билет {ticket['ticket_id']:2d}: "
            f"{len(ticket['situations'])} ситуаций"
        )

    print()
    print(f"Файл: {OUTPUT_FILE}")


def main():
    print("Загрузка tickets_32.txt...")

    if not INPUT_FILE.exists():
        raise FileNotFoundError(
            f"Не найден файл:\n{INPUT_FILE}"
        )

    text = INPUT_FILE.read_text(
        encoding="utf-8"
    )

    tickets = parse_tickets(text)

    errors = validate_tickets(tickets)

    print_summary(tickets)

    print()
    print("=" * 60)
    print("ПРОВЕРКА")
    print("=" * 60)

    if errors:
        print("Найдены проблемы:")

        for error in errors:
            print(f"  ❌ {error}")

        print()
        print("JSON НЕ сохранён.")
        return

    print("✓ 32 билета присутствуют.")
    print("✓ 96 ситуаций присутствуют.")
    print("✓ У всех ситуаций есть описание.")
    print("✓ У всех ситуаций есть адрес.")
    print("✓ Структура корректна.")

    save_tickets(tickets)

    print()
    print(f"✓ JSON сохранён: {OUTPUT_FILE}")


if __name__ == "__main__":
    main()
