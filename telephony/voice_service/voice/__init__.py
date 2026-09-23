"""voice — сменные STT/TTS-модули этапа 5.

Контракты:
    Audio -> STT -> Text   (voice.stt.STTEngine.transcribe)
    Text  -> TTS -> Audio  (voice.tts.TTSEngine.synthesize)

Реализация выбирается переменными окружения STT_ENGINE / TTS_ENGINE
(см. voice.config), код, вызывающий движок, от реализации не зависит.
"""
