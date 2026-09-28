"""Маршруты интеграции ML-сервиса с телефонией и Backend.

Подключаются в api.py одной строкой (app.include_router), основная логика ML не меняется.

    POST /dialogue/turn                 реплика виртуального собеседника (telephony/API.md §3)
    GET  /dialogue/health               движок реплик и сценарии 112
    POST /api/v1/generate/scenarios     генерация сценариев по классификатору (backend INTEGRATION.md §1)
    POST /api/v1/evaluate/attempt       оценка ответа по сценарию ML
    POST /api/v1/generate/correct       } пока не реализованы в ML -> 501,
    POST /api/v1/analyze/grammar        } backend считает по своим правилам
    POST /api/v1/analytics/summary      }
    POST /api/v1/recommendations        }
    POST /api/v1/knowledge/index        }
"""

import logging
from typing import Any, Callable, Dict

from fastapi import APIRouter, Body, HTTPException

from . import backend_contract, dialogue

log = logging.getLogger("ml.integration")

NOT_IMPLEMENTED = ("generate/correct", "analyze/grammar", "analytics/summary", "recommendations", "knowledge/index")


def build_router(classifier_data: Any, classify: Callable[[str], Dict[str, Any]]) -> APIRouter:
    router = APIRouter(tags=["Интеграция: телефония и Backend"])
    scenarios = dialogue.load_scenarios()
    llm = dialogue.LLMConfig.from_env()
    log.info("реплики собеседников: %s, сценарии 112: %s",
             f"LLM {llm.model} @ {llm.api_url}" if llm else "правила", ", ".join(sorted(scenarios)))

    @router.post("/dialogue/turn")
    def dialogue_turn(req: Dict[str, Any] = Body(...)):
        try:
            reply = dialogue.next_turn(req, scenarios, llm)
        except dialogue.DialogueError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc
        log.info("dialogue %s call_id=%s turn=%s -> end=%s [%s]", req.get("call_type"), req.get("call_id"),
                 req.get("turn"), reply["end_call"], reply.get("engine"))
        return reply

    @router.get("/dialogue/health")
    def dialogue_health():
        return {"status": "ok", "engine": f"llm:{llm.model}" if llm else "rules", "scenarios": sorted(scenarios)}

    @router.post("/api/v1/generate/scenarios")
    def generate_scenarios(payload: Dict[str, Any] = Body(...)):
        try:
            return backend_contract.generate_scenarios(payload, classifier_data, classify)
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

    @router.post("/api/v1/evaluate/attempt")
    def evaluate_attempt(payload: Dict[str, Any] = Body(...)):
        try:
            return backend_contract.evaluate_attempt(payload)
        except backend_contract.NotImplementedByML as exc:
            raise HTTPException(status_code=501, detail=str(exc)) from exc
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

    for path in NOT_IMPLEMENTED:
        router.add_api_route(f"/api/v1/{path}", _not_implemented(path), methods=["POST"])

    return router


def _not_implemented(path: str):
    def handler(_: Dict[str, Any] = Body(default={})):
        raise HTTPException(status_code=501, detail=f"/api/v1/{path} пока не реализован в ML-сервисе")
    return handler
