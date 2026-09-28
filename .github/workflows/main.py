
from classifier import (
    load_classifier,
    get_incidents_by_category,
    get_groups_by_category,
    validate_classifier,
)
from scenario_generator import generate_scenario
from evaluator import evaluate_answer




classifier_data = load_classifier()

print("Классификатор загружен.")
print("Категорий:", len(classifier_data["categories"]))
print("Инцидентов:", len(classifier_data["incidents"]))
print("Групп:", len(classifier_data["groups"]))
print(
    "Строк без итогового типа:",
    len(classifier_data["rows_without_incident_type"]),
)



errors = validate_classifier(classifier_data)

if errors:
    print("\nОбнаружены проблемы:")
    for error in errors[:20]:
        print("-", error)
    if len(errors) > 20:
        print("И другие ошибки:", len(errors) - 20)
else:
    print("\nБазовые проверки пройдены.")


traffic_incidents = get_incidents_by_category(classifier_data, 2)

print("\nПервые пять инцидентов категории ДТП:")
for incident in traffic_incidents[:5]:
    print(incident)

print("\nВсего инцидентов категории ДТП:", len(traffic_incidents))




traffic_groups = get_groups_by_category(classifier_data, 2)

print("\nГруппы категории ДТП:")
for group in traffic_groups:
    print(
        group["name"],
        "| Инцидентов:",
        len(group["incidents"]),
    )



scenario = generate_scenario(
    classifier_data=classifier_data,
    incident_number="14101600",   # «Нет света в кабине лифта»
    difficulty="medium",
)

print("\n=== Сгенерированный сценарий ===")
print("ID:          ", scenario["scenario_id"])
print("Сложность:   ", scenario["difficulty"])
print("Тема:        ", scenario["title"])
print("Описание:    ", scenario["description"])
print("Классификация:", scenario["classification"])
print("Статус:      ", scenario["status"])
print("Критерии:    ", scenario["metadata"]["criteria_ids"])



test_answers = {
    "Полный ответ": (
        "Здравствуйте. Назовите точный адрес. Что произошло? "
        "Когда это случилось? Есть ли пострадавшие? "
        "Есть ли люди в кабине лифта? Открываются ли двери лифта? "
        "Есть ли дополнительные обстоятельства?"
    ),
    "Частичный": (
        "Здравствуйте. Что случилось? Есть ли пострадавшие?"
    ),
    "Пустой по смыслу": (
        "Алло, я вас слушаю, говорите."
    ),
    "Ложный (не должно засчитаться)": (
        "Я сейчас уточню у вас адрес. Пожарная служба уже "
        "выехала на место происшествия."
    ),
}

print("\n=== Результаты оценки ===")
for name, ans in test_answers.items():
    result = evaluate_answer(scenario=scenario, operator_answer=ans)
    print(f"\n--- {name} ---")
    print("score:        ", result["score"])
    print("correct:      ", len(result["correct_actions"]))
    print("missed:       ", len(result["missed_actions"]))
    print("mistakes:     ", result["mistakes"])
    print("feedback:     ", result["feedback"])
    print("debug.answer: ", result["debug"]["answer"][:80], "...")