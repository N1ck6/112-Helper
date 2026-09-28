from typing import Any, Dict, List, Optional

from fastapi import FastAPI, HTTPException
from pydantic import BaseModel, Field

from classifier import load_classifier
from matcher import match_situation, prepare_incidents
from llm_processor import analyze_text
from scenario_generator import generate_scenario
from evaluator import evaluate_answer
from integration import build_router


app = FastAPI(
    title="System-112 AI Training Service",
    version="2.0.0",
)





print("Загрузка классификатора...")

classifier_data = load_classifier()
INCIDENTS = prepare_incidents(classifier_data)

print("Классификатор загружен.")
print(f"Категорий: {len(classifier_data['categories'])}")
print(f"Инцидентов: {len(classifier_data['incidents'])}")





class TextRequest(BaseModel):
    text: str = Field(..., min_length=1)


class ScenarioRequest(BaseModel):
    difficulty: str = Field(
        default="medium",
        description="easy / medium / hard"
    )
    incident_number: Optional[str] = Field(
        default=None,
        description="Официальный номер инцидента из классификатора"
    )


class EvaluationRequest(BaseModel):
    scenario: Dict[str, Any]
    operator_answer: str = Field(..., min_length=1)




def _safe_float(value: Any, default: float = 0.0) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def _incident_from_alternative(alternative: Dict[str, Any]) -> Dict[str, Any]:


    incident = alternative.get("incident")

    if not isinstance(incident, dict):
        incident = alternative

    return {
        "incident_number": incident.get("number"),
        "category_number": incident.get("category_number"),
        "category": incident.get("category"),
        "group": incident.get("group"),
        "incident_type": incident.get("incident_type"),
        "ekp35_type": incident.get("ekp35_type"),
        "main_service": incident.get("main_service"),
        "score": _safe_float(
            alternative.get("score", incident.get("score", 0))
        ),
    }


def build_classification_response(result: Dict[str, Any]) -> Dict[str, Any]:

    best = result.get("best_match")

    response = {
        "status": result.get("status"),
        "primary_event": result.get("primary_event"),
        "event_types": result.get("event_types", []),

        "category_number": None,
        "category": None,
        "group": None,

        "incident_number": None,
        "incident_type": None,
        "ekp35_type": None,
        "main_service": None,

        "score": _safe_float(result.get("score")),
        "margin": _safe_float(result.get("margin")),

        "alternatives": [],
    }

    if isinstance(best, dict):
        best_incident = best.get("incident")

        if isinstance(best_incident, dict):
            best = best_incident

        response.update({
            "category_number": best.get("category_number"),
            "category": best.get("category"),
            "group": best.get("group"),

            "incident_number": best.get("number"),
            "incident_type": best.get("incident_type"),
            "ekp35_type": best.get("ekp35_type"),
            "main_service": best.get("main_service"),
        })

    alternatives = result.get("alternatives", [])

    for alternative in alternatives[:3]:
        if isinstance(alternative, dict):
            response["alternatives"].append(
                _incident_from_alternative(alternative)
            )

    return response


def run_classification(text: str) -> Dict[str, Any]:
    result = match_situation(
        description=text,
        incidents=INCIDENTS,
    )

    return build_classification_response(result)


# Контракты для телефонии (/dialogue/turn) и Backend (/api/v1/...) — integration/routes.py
app.include_router(build_router(classifier_data, run_classification))


@app.get("/health")
def health():
    return {
        "status": "ok",
        "service": "system-112-ai",
        "classifier_loaded": True,
        "incidents": len(INCIDENTS),
        "categories": len(classifier_data["categories"]),
        "llm": "qwen3:4b",
    }




@app.post("/classify")
def classify(request: TextRequest):

    text = request.text.strip()

    if not text:
        raise HTTPException(
            status_code=400,
            detail="Поле text не должно быть пустым",
        )

    return run_classification(text)




@app.post("/analyze")
def analyze(request: TextRequest):

    text = request.text.strip()

    if not text:
        raise HTTPException(
            status_code=400,
            detail="Поле text не должно быть пустым",
        )

    try:
        llm_result = analyze_text(text)

    except Exception as error:
        raise HTTPException(
            status_code=503,
            detail=f"Ошибка локальной LLM: {error}",
        ) from error

    return {
        "text": text,
        "facts": llm_result.get("facts", []),
        "unknowns": llm_result.get("unknowns", []),
        "summary": llm_result.get("summary", ""),
    }




@app.post("/classify_with_llm")
def classify_with_llm(request: TextRequest):

    text = request.text.strip()

    if not text:
        raise HTTPException(
            status_code=400,
            detail="Поле text не должно быть пустым",
        )





    try:
        llm_result = analyze_text(text)

    except Exception as error:
        raise HTTPException(
            status_code=503,
            detail=f"Ошибка локальной LLM: {error}",
        ) from error




    classification = run_classification(text)


    return {
        "text": text,

        "llm": {
            "facts": llm_result.get("facts", []),
            "unknowns": llm_result.get("unknowns", []),
            "summary": llm_result.get("summary", ""),
        },

        "classification": classification,
    }



@app.post("/generate_scenario")
def generate_training_scenario(request: ScenarioRequest):

    difficulty = request.difficulty.lower().strip()

    if difficulty not in {"easy", "medium", "hard"}:
        raise HTTPException(
            status_code=400,
            detail="difficulty должен быть easy, medium или hard",
        )

    try:
        scenario = generate_scenario(
            classifier_data=classifier_data,
            difficulty=difficulty,
            incident_number=request.incident_number,
        )

    except ValueError as error:
        raise HTTPException(
            status_code=400,
            detail=str(error),
        ) from error

    except Exception as error:
        raise HTTPException(
            status_code=500,
            detail=f"Ошибка генерации сценария: {error}",
        ) from error

    return scenario



@app.post("/evaluate")
def evaluate_operator_answer(request: EvaluationRequest):

    answer = request.operator_answer.strip()

    if not answer:
        raise HTTPException(
            status_code=400,
            detail="operator_answer не должен быть пустым",
        )

    try:
        result = evaluate_answer(
            scenario=request.scenario,
            operator_answer=answer,
        )

    except ValueError as error:
        raise HTTPException(
            status_code=400,
            detail=str(error),
        ) from error

    except Exception as error:
        raise HTTPException(
            status_code=500,
            detail=f"Ошибка оценки ответа: {error}",
        ) from error

    return result
