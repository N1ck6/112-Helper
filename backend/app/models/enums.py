from __future__ import annotations

from enum import StrEnum


class UserStatus(StrEnum):
    ACTIVE = "active"
    BLOCKED = "blocked"
    PENDING = "pending"


class DifficultyLevel(StrEnum):
    """Уровни сложности заданий (п.2.4)."""

    BASIC = "basic"
    MEDIUM = "medium"
    HARD = "hard"


class MaterialKind(StrEnum):
    """Первичные данные из п.11 ТЗ."""

    MEMO = "memo"              # памятка «Работа на АРМ-112»
    CLASSIFIER = "classifier"  # классификатор происшествий
    TICKET = "ticket"          # билеты и задачи
    DOC = "doc"
    AUDIO = "audio"
    OTHER = "other"


class ScenarioStatus(StrEnum):
    DRAFT = "draft"
    PENDING_REVIEW = "pending_review"
    APPROVED = "approved"
    ARCHIVED = "archived"


class ScenarioOrigin(StrEnum):
    MANUAL = "manual"
    AI_GENERATED = "ai_generated"
    AI_CORRECTED = "ai_corrected"


class GenerationStatus(StrEnum):
    QUEUED = "queued"
    IN_PROGRESS = "in_progress"
    READY = "ready"
    FAILED = "failed"


class CardOrigin(StrEnum):
    """Источник карточки — п.2.5: сгенерированные, созданные обучающимися, смешанно."""

    GENERATED = "generated"
    STUDENT = "student"
    MANUAL = "manual"


class CardSource(StrEnum):
    """Выбор преподавателя при запуске занятия во втором режиме."""

    GENERATED = "generated"
    STUDENT = "student"
    MIXED = "mixed"


class CardStatus(StrEnum):
    DRAFT = "draft"
    READY = "ready"
    ARCHIVED = "archived"


class LessonMode(StrEnum):
    """Два сценария занятия из п.10 ТЗ."""

    CARD_FILL = "card_fill"      # заполнение карточки по имитации вызова
    CARD_ACTION = "card_action"  # действия с уже сформированными карточками


class LessonPurpose(StrEnum):
    """Вид мероприятия (п.2.4 ТЗ: аттестация и периодическая переподготовка)."""

    TRAINING = "training"          # учебное занятие
    ATTESTATION = "attestation"    # аттестационное мероприятие с зачётом
    REFRESHER = "refresher"        # периодическая переподготовка действующих операторов


LESSON_PURPOSE_TITLES: dict[LessonPurpose, str] = {
    LessonPurpose.TRAINING: "Учебное занятие",
    LessonPurpose.ATTESTATION: "Аттестационное мероприятие",
    LessonPurpose.REFRESHER: "Периодическая переподготовка",
}


class LessonStatus(StrEnum):
    PLANNED = "planned"
    RUNNING = "running"
    PAUSED = "paused"
    FINISHED = "finished"
    ABORTED = "aborted"


class ParticipantStatus(StrEnum):
    INVITED = "invited"
    ONLINE = "online"
    RECONNECTING = "reconnecting"
    OFFLINE = "offline"
    FINISHED = "finished"


class AttemptStatus(StrEnum):
    ISSUED = "issued"
    IN_PROGRESS = "in_progress"
    SUBMITTED = "submitted"
    EVALUATED = "evaluated"
    EXPIRED = "expired"
    SKIPPED = "skipped"


class ActionType(StrEnum):
    """Фиксируемые действия оператора (п.2.5: последовательность действий)."""

    CALL_ACCEPTED = "call_accepted"
    FIELD_FILLED = "field_filled"
    TEXT_ENTERED = "text_entered"
    CLASSIFIED = "classified"
    ROUTED_TO_DDS = "routed_to_dds"
    CARD_SAVED = "card_saved"
    CARD_SUBMITTED = "card_submitted"
    CARD_SKIPPED = "card_skipped"
    CALL_ENDED = "call_ended"
    NOTE_ADDED = "note_added"
    #: Простановка статуса реагирования на АРМ-112 (режим «действия с карточками»).
    RESPONSE_STATUS_SET = "response_status_set"


class ResponseStatus(StrEnum):
    ADDED = "added"                        # Добавлена — техническая отметка при оповещении службы
    RECEIVED = "received"                  # Получена службой — карточка открыта на АРМ-112
    ACCEPTED = "accepted"                  # Принята — реагирование будет осуществляться
    NOT_ACCEPTED = "not_accepted"          # Не принята — реагирования не будет (нужен комментарий)
    RESPONSE_STARTED = "response_started"  # Начало реагирования — выезд сил и средств
    ARRIVED = "arrived"                    # Прибытие на место происшествия
    WORK_IN_PROGRESS = "work_in_progress"  # Проведение аварийно-восстановительных работ
    WORK_COMPLETED = "work_completed"      # Работы завершены — закрывает карточку
    WORK_REFUSED = "work_refused"          # Отказ от выполнения работ (нужен комментарий)


RESPONSE_STATUS_TITLES: dict[ResponseStatus, str] = {
    ResponseStatus.ADDED: "Добавлена",
    ResponseStatus.RECEIVED: "Получена службой",
    ResponseStatus.ACCEPTED: "Принята",
    ResponseStatus.NOT_ACCEPTED: "Не принята",
    ResponseStatus.RESPONSE_STARTED: "Начало реагирования",
    ResponseStatus.ARRIVED: "Прибытие",
    ResponseStatus.WORK_IN_PROGRESS: "Проведение работ",
    ResponseStatus.WORK_COMPLETED: "Работы завершены",
    ResponseStatus.WORK_REFUSED: "Отказ от выполнения работ",
}

RESPONSE_STATUS_TRANSITIONS: dict[ResponseStatus, tuple[ResponseStatus, ...]] = {
    ResponseStatus.ADDED: (ResponseStatus.RECEIVED,),
    ResponseStatus.RECEIVED: (ResponseStatus.ACCEPTED, ResponseStatus.NOT_ACCEPTED),
    ResponseStatus.NOT_ACCEPTED: (ResponseStatus.ACCEPTED,),
    ResponseStatus.ACCEPTED: (
        ResponseStatus.RESPONSE_STARTED,
        ResponseStatus.ARRIVED,
        ResponseStatus.WORK_IN_PROGRESS,
        ResponseStatus.WORK_COMPLETED,
        ResponseStatus.WORK_REFUSED,
    ),
    ResponseStatus.RESPONSE_STARTED: (
        ResponseStatus.ARRIVED,
        ResponseStatus.WORK_IN_PROGRESS,
        ResponseStatus.WORK_COMPLETED,
        ResponseStatus.WORK_REFUSED,
    ),
    ResponseStatus.ARRIVED: (
        ResponseStatus.WORK_IN_PROGRESS,
        ResponseStatus.WORK_COMPLETED,
        ResponseStatus.WORK_REFUSED,
    ),
    ResponseStatus.WORK_IN_PROGRESS: (
        ResponseStatus.WORK_COMPLETED,
        ResponseStatus.WORK_REFUSED,
    ),
    ResponseStatus.WORK_COMPLETED: (),
    ResponseStatus.WORK_REFUSED: (),
}

#: Первичные статусы: норматив 30 секунд относится именно к ним (ПП РФ № 1931).
PRIMARY_RESPONSE_STATUSES = frozenset({ResponseStatus.ACCEPTED, ResponseStatus.NOT_ACCEPTED})

#: Комментарий обязателен — без указания причины отказ считается нарушением.
COMMENT_REQUIRED_STATUSES = frozenset({ResponseStatus.NOT_ACCEPTED, ResponseStatus.WORK_REFUSED})

#: Закрывают карточку для редактирования.
TERMINAL_RESPONSE_STATUSES = frozenset({ResponseStatus.WORK_COMPLETED, ResponseStatus.WORK_REFUSED})

#: Статусы хода выполнения работ — их отсутствие является нарушением.
PROGRESS_RESPONSE_STATUSES = (
    ResponseStatus.RESPONSE_STARTED,
    ResponseStatus.ARRIVED,
    ResponseStatus.WORK_IN_PROGRESS,
)

#: Статусы, которые система проставляет сама.
SYSTEM_RESPONSE_STATUSES = frozenset({ResponseStatus.ADDED, ResponseStatus.RECEIVED})


class CardLifecycleStatus(StrEnum):
    """Статус карточки происшествия в системе-112 (памятка, раздел о нарушениях)."""

    REGISTERED = "registered"        # Зарегистрирована
    PROCESSED = "processed"          # Отработана
    CHECKED = "checked"              # Проверена
    NOT_NOTIFIED = "not_notified"    # Не оповещено — нет первичного статуса вовремя
    REFUSAL = "refusal"              # Отказ — «Не принята» или «Отказ от выполнения работ»
    NOT_FINISHED = "not_finished"    # Не завершено — нет «Работы завершены» спустя 48 часов
    COMPLETED = "completed"          # Завершена


class ErrorCategory(StrEnum):
    TIMING = "timing"
    PROCEDURE = "procedure"
    DATA_ACCURACY = "data_accuracy"
    CLASSIFICATION = "classification"
    COMPLETENESS = "completeness"
    GRAMMAR = "grammar"
    SYNTAX = "syntax"


class ErrorSeverity(StrEnum):
    MINOR = "minor"
    MAJOR = "major"
    CRITICAL = "critical"


class EvaluationSource(StrEnum):
    AI = "ai"
    TEACHER = "teacher"
    SYSTEM = "system"


class MLTaskKind(StrEnum):
    GENERATION = "generation"
    CORRECTION = "correction"
    EVALUATION = "evaluation"
    GRAMMAR = "grammar"
    ANALYTICS = "analytics"
    RECOMMENDATION = "recommendation"


class MLTaskStatus(StrEnum):
    OK = "ok"
    FAILED = "failed"
    STUBBED = "stubbed"


class RecommendationTarget(StrEnum):
    STUDENT = "student"
    GROUP = "group"
    TEACHER = "teacher"


class ReportType(StrEnum):
    LESSON = "lesson"
    PROGRESS = "progress"
    GROUP_STATS = "group_stats"
    ERRORS = "errors"
    TIMING = "timing"
    AUDIT = "audit"
    ATTESTATION = "attestation"  # протокол аттестации (п.2.4, 2.6)


class ReportFormat(StrEnum):
    JSON = "json"
    CSV = "csv"
    PDF = "pdf"
    XLSX = "xlsx"  # опциональный модуль Excel (п.2.6 ТЗ)
    XML = "xml"    # обмен с legacy-системами (п.2.1, 2.9 ТЗ)


class ReportStatus(StrEnum):
    PENDING = "pending"
    READY = "ready"
    FAILED = "failed"


class AuditAction(StrEnum):
    LOGIN = "login"
    LOGIN_FAILED = "login_failed"
    LOGOUT = "logout"
    CREATE = "create"
    UPDATE = "update"
    DELETE = "delete"
    BLOCK = "block"
    UNBLOCK = "unblock"
    PERMISSION_CHANGE = "permission_change"
    GRADE_OVERRIDE = "grade_override"
    LESSON_START = "lesson_start"
    LESSON_FINISH = "lesson_finish"
    EXPORT = "export"
    SERVICE_CONTROL = "service_control"
    CONFIG_CHANGE = "config_change"
    BACKUP = "backup"


class LogLevel(StrEnum):
    DEBUG = "debug"
    INFO = "info"
    WARNING = "warning"
    ERROR = "error"
    CRITICAL = "critical"


class ServiceStatus(StrEnum):
    RUNNING = "running"
    STOPPED = "stopped"
    DEGRADED = "degraded"
    UNKNOWN = "unknown"


class BackupStatus(StrEnum):
    STARTED = "started"
    SUCCESS = "success"
    FAILED = "failed"


class ProcessingKind(StrEnum):
    SERVICE = "service"          # звонок в службу списка оповещения
    SUPERVISOR = "supervisor"    # доклад руководителю / должностному лицу службы
    BRIGADE = "brigade"          # вызов бригады, разговор со старшим группы
    APPLICANT = "applicant"      # звонок заявителю по номеру из карточки
    INCOMING_REPORT = "incoming_report"  # входящий доклад старшего группы в ДДС


class ServiceLevel(StrEnum):
    EMERGENCY = "emergency"      # экстренная оперативная служба (101–104)
    DEPARTMENT = "department"     # ДДС департамента или ведомства
    DISTRICT = "district"         # ДДС управы района
    OKRUG = "okrug"               # ДДС административного округа
    UTILITY = "utility"           # аварийная служба городского хозяйства
    OTHER = "other"


class CallDirection(StrEnum):
    INBOUND = "inbound"
    OUTBOUND = "outbound"


class CallStatus(StrEnum):
    RINGING = "ringing"
    ANSWERED = "answered"
    MISSED = "missed"
    ENDED = "ended"
    FAILED = "failed"


class OutboxStatus(StrEnum):
    PENDING = "pending"
    SENT = "sent"
    FAILED = "failed"
    DEAD = "dead"
