from pathlib import Path

import pandas as pd


# ============================================================
# 1. Настройки
# ============================================================

CLASSIFIER_PATH = Path("data/raw/Klassifikator.xlsx")

DATA_START_ROW = 4

# Индексы нужных столбцов Excel
COL_CATEGORY_CODE = 0
COL_NUMBER = 4
COL_GROUP = 5
COL_FEATURE_1 = 6
COL_FEATURE_2 = 7
COL_FEATURE_3 = 8
COL_ADDITIONAL_FEATURES = 9
COL_INCIDENT_TYPE = 10
COL_EKP35_TYPE = 11
COL_MAIN_SERVICE = 12


# ============================================================
# 2. Вспомогательные функции
# ============================================================

def clean_value(value):
    """
    Приводит значение Excel к строке.
    Пустые значения преобразует в None.
    """

    if pd.isna(value):
        return None

    value = str(value).strip()

    if not value:
        return None

    return value


def clean_integer(value):
    """
    Безопасно преобразует значение в целое число.
    Если преобразование невозможно, возвращает None.
    """

    if pd.isna(value):
        return None

    try:
        return int(value)
    except (ValueError, TypeError, OverflowError):
        return None


# ============================================================
# 3. Чтение исходного Excel
# ============================================================

def load_excel(file_path=CLASSIFIER_PATH):
    """
    Загружает исходный классификатор Excel.

    Возвращает DataFrame с исходными данными.
    """

    if not file_path.exists():
        raise FileNotFoundError(
            f"Файл классификатора не найден: {file_path.resolve()}"
        )

    df = pd.read_excel(file_path, header=None)

    if df.empty:
        raise ValueError("Файл классификатора пуст.")

    required_column = COL_MAIN_SERVICE

    if df.shape[1] <= required_column:
        raise ValueError(
            "В Excel недостаточно столбцов для обработки классификатора."
        )

    return df


# ============================================================
# 4. Получение категорий
# ============================================================

def extract_categories(df):
    """
    Извлекает верхнеуровневые категории.

    Категория определяется по строке, в которой:
    - в столбце 4 указан номер от 1 до 24;
    - в столбце 5 указано название;
    - в столбце 0 отсутствует код инцидента.

    Категория 24 «БПЛА» пока обрабатывается отдельно,
    поскольку в изученной структуре Excel для неё
    не обнаружена обычная строка-заголовок.
    """

    categories = {}

    for _, row in df.iloc[3:].iterrows():

        number = clean_integer(row[COL_NUMBER])
        name = clean_value(row[COL_GROUP])
        code = clean_value(row[COL_CATEGORY_CODE])

        if number is None or name is None:
            continue

        if 1 <= number <= 24 and code is None:
            categories[number] = name

    if 24 not in categories:
        categories[24] = "БПЛА"

    return categories


# ============================================================
# 5. Нормализация одного инцидента
# ============================================================

def normalize_incident(row, categories):
    """
    Преобразует строку Excel в структурированный словарь.
    """

    category_number = clean_integer(row[COL_CATEGORY_CODE])

    category = categories.get(category_number)

    features = [
        clean_value(row[COL_FEATURE_1]),
        clean_value(row[COL_FEATURE_2]),
        clean_value(row[COL_FEATURE_3]),
    ]

    features = [
        feature
        for feature in features
        if feature is not None
    ]

    return {
        "number": clean_value(row[COL_NUMBER]),
        "category_number": category_number,
        "category": category,
        "group": clean_value(row[COL_GROUP]),
        "features": features,
        "additional_features": clean_value(
            row[COL_ADDITIONAL_FEATURES]
        ),
        "incident_type": clean_value(row[COL_INCIDENT_TYPE]),
        "ekp35_type": clean_value(row[COL_EKP35_TYPE]),
        "main_service": clean_value(row[COL_MAIN_SERVICE]),
    }
# ============================================================
# 5.1. Построение групп на основе реальных инцидентов
# ============================================================

def extract_groups(incidents):
    """
    Формирует список уникальных групп на основе реальных инцидентов.

    Группа определяется сочетанием:
    - номера категории;
    - названия группы.

    Это позволяет не принимать строки-заголовки Excel
    за полноценные группы.
    """

    groups = {}

    for incident in incidents:

        category_number = incident["category_number"]
        category = incident["category"]
        group_name = incident["group"]

        # Без категории или названия группы
        # полноценную группу сформировать нельзя.
        if category_number is None or group_name is None:
            continue

        group_key = (category_number, group_name)

        if group_key not in groups:
            groups[group_key] = {
                "category_number": category_number,
                "category": category,
                "name": group_name,
                "incidents": [],
            }

        groups[group_key]["incidents"].append(incident)

    return list(groups.values())

# ============================================================
# 6. Загрузка и нормализация классификатора
# ============================================================

def load_classifier(file_path=CLASSIFIER_PATH):
    """
    Загружает Excel и возвращает структурированный классификатор.

    На этом этапе строки без incident_type сохраняются отдельно:
    мы пока не считаем их автоматически полноценными группами,
    поскольку в исходной таблице встречаются строки категорий.
    """

    df = load_excel(file_path)

    categories = extract_categories(df)

    data = df.iloc[DATA_START_ROW:].copy()

    # Сохраняем прежний способ заполнения названия группы.
    # Иерархию групп отдельно проверим на следующем этапе.
    data[COL_GROUP] = data[COL_GROUP].ffill()

    normalized_rows = []

    for _, row in data.iterrows():
        normalized_rows.append(
            normalize_incident(row, categories)
        )

    incidents = [
        item
        for item in normalized_rows
        if item["incident_type"] is not None
    ]

    rows_without_incident_type = [
        item
        for item in normalized_rows
        if item["incident_type"] is None
    ]

    groups = extract_groups(incidents)

    return {
        "categories": categories,
        "groups": groups,
        "incidents": incidents,
        "rows_without_incident_type": rows_without_incident_type,
    }


# ============================================================
# 7. Поиск инцидентов
# ============================================================

def get_incidents_by_category(classifier_data, category_number):
    """
    Возвращает инциденты указанной категории.
    """

    return [
        incident
        for incident in classifier_data["incidents"]
        if incident["category_number"] == category_number
    ]
def get_groups_by_category(classifier_data, category_number):
    """
    Возвращает группы указанной категории.
    """

    return [
        group
        for group in classifier_data["groups"]
        if group["category_number"] == category_number
    ]



def get_incidents_by_group(classifier_data, group_name):
    """
    Возвращает инциденты указанной группы.

    Поиск выполняется по точному названию группы.
    """

    return [
        incident
        for incident in classifier_data["incidents"]
        if incident["group"] == group_name
    ]


def get_incidents_by_type(classifier_data, incident_type):
    """
    Возвращает инциденты с указанным итоговым типом.
    """

    return [
        incident
        for incident in classifier_data["incidents"]
        if incident["incident_type"] == incident_type
    ]


# ============================================================
# 8. Проверка структуры данных
# ============================================================

def validate_classifier(classifier_data):
    """
    Проверяет базовую целостность классификатора.

    Возвращает список обнаруженных проблем.
    """

    errors = []

    categories = classifier_data["categories"]
    incidents = classifier_data["incidents"]

    if not categories:
        errors.append("Не удалось извлечь категории.")

    if not incidents:
        errors.append("Не удалось извлечь реальные инциденты.")

    for index, incident in enumerate(incidents):

        if incident["incident_type"] is None:
            errors.append(
                f"У инцидента с индексом {index} отсутствует тип."
            )

        if incident["category_number"] is None:
            errors.append(
                f"У инцидента с индексом {index} отсутствует номер категории."
            )

        elif incident["category_number"] not in categories:
            errors.append(
                f"У инцидента с индексом {index} неизвестная категория: "
                f"{incident['category_number']}."
            )

    return errors
