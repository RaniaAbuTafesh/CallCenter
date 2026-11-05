#
# Pipecat voice demo - OpenAI only (speech-to-text, LLM and text-to-speech).
# Based on examples/voice/voice-openai.py, trimmed to the browser (WebRTC)
# transport so it needs no Daily / LiveKit / Deepgram / Cartesia accounts.
#
# Run from the repo root:   uv run demo_bot.py -t webrtc
# Then open:                http://localhost:7860/  (branded page; stock page at /client/)
#

import os

import aiohttp
from dotenv import load_dotenv
from loguru import logger

from pipecat.frames.frames import LLMRunFrame
from pipecat.pipeline.pipeline import Pipeline
from pipecat.pipeline.worker import PipelineParams, PipelineWorker, ProcessorUnusablePolicy
from pipecat.processors.aggregators.llm_context import LLMContext
from pipecat.processors.aggregators.llm_response_universal import (
    LLMContextAggregatorPair,
    LLMUserAggregatorParams,
)
from pipecat.runner.types import RunnerArguments
from pipecat.runner.utils import create_transport
from pipecat.services.llm_service import FunctionCallParams
from pipecat.transports.base_transport import BaseTransport, TransportParams
from pipecat.workers.runner import WorkerRunner

load_dotenv(override=True)

# Which AI runs the call. With a Gemini key the bot uses Gemini Live (one model
# that listens, thinks and speaks); otherwise it uses OpenAI (STT + LLM + TTS).
# Force one with AI_PROVIDER=gemini or AI_PROVIDER=openai.
GOOGLE_API_KEY = (os.getenv("GOOGLE_API_KEY") or os.getenv("GEMINI_API_KEY") or "").strip()
OPENAI_API_KEY = (os.getenv("OPENAI_API_KEY") or "").strip()
AI_PROVIDER = (os.getenv("AI_PROVIDER") or "").strip().lower() or ("gemini" if GOOGLE_API_KEY else "openai")
if AI_PROVIDER not in ("gemini", "openai"):
    raise SystemExit(f"AI_PROVIDER must be 'gemini' or 'openai', not '{AI_PROVIDER}'.")
if AI_PROVIDER == "gemini" and not GOOGLE_API_KEY:
    raise SystemExit("GOOGLE_API_KEY is missing. Put your Gemini key in the .env file (or in Render > Environment).")
if AI_PROVIDER == "openai" and not OPENAI_API_KEY:
    raise SystemExit("No AI key found. Add GOOGLE_API_KEY (Gemini) or OPENAI_API_KEY to the .env file.")
logger.info(f"AI provider: {AI_PROVIDER}")

# Only the browser (WebRTC) transport, so no extra accounts are needed.
transport_params = {
    "webrtc": lambda: TransportParams(
        audio_in_enabled=True,
        audio_out_enabled=True,
    ),
}

# n8n workflow that stores questions the bot could not answer (data table
# raghad_unanswered_questions). Override with N8N_WEBHOOK_URL if it moves.
N8N_WEBHOOK_URL = os.getenv(
    "N8N_WEBHOOK_URL", "https://n8n.zyndeskjo.com/webhook/raghad-unanswered-question"
).strip()

# Call-center knowledge base (Raghad Organics). Lives next to this script.
KNOWLEDGE_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "raghad_organics_knowledge.txt")
try:
    with open(KNOWLEDGE_FILE, encoding="utf-8") as f:
        KNOWLEDGE = f.read()
    logger.info(f"Loaded knowledge base: {KNOWLEDGE_FILE}")
except FileNotFoundError:
    KNOWLEDGE = ""
    logger.warning(f"Knowledge file not found: {KNOWLEDGE_FILE}")

SYSTEM_PROMPT = (
    "You are the voice call-center agent for Raghad Organics Jordan (رغد أورجانكس). "
    "Speak in friendly Jordanian Arabic by default; switch to English only if the caller speaks English. "
    "Your replies are spoken aloud, so never use emojis, bullet points, lists or other formatting, "
    "and keep each answer to one to three short sentences. Say prices in words like 'تسعة دنانير'. "
    "Answer ONLY from the knowledge base below. Never invent prices, policies or medical advice.\n"
    "If the caller asks a real question about Raghad Organics (products, prices, orders, delivery, branches, "
    "services, the company) and the answer is NOT in the knowledge base, first call the function "
    "log_unanswered_question once for that question, then tell the caller briefly that you don't have this "
    "information right now, that you noted the question for the team, and that they can call 06 222 2700. "
    "Do not call it for greetings, small talk, or questions you can answer from the knowledge base.\n\n"
    "=== KNOWLEDGE BASE ===\n" + KNOWLEDGE
)


async def run_bot(transport: BaseTransport, runner_args: RunnerArguments):
    logger.info(f"Starting demo bot ({AI_PROVIDER})")
    session_id = str(getattr(runner_args, "session_id", "") or "")

    async def log_unanswered_question(
        params: FunctionCallParams, question: str, topic: str = "other", customer_words: str = ""
    ):
        """Record a customer question that the knowledge base cannot answer, so the team can add the answer later.

        Args:
            question: The customer's question rewritten as one clear, complete sentence in Arabic.
            topic: One of: products, prices, delivery, payment, returns, branches, aminotherapy, company, other.
            customer_words: What the customer actually said, as close to their words as possible.
        """
        payload = {
            "question": question,
            "topic": topic,
            "customer_words": customer_words,
            "session_id": session_id,
            "source": "voice-bot",
        }
        saved = False
        if N8N_WEBHOOK_URL:
            try:
                async with aiohttp.ClientSession(timeout=aiohttp.ClientTimeout(total=8)) as http:
                    async with http.post(N8N_WEBHOOK_URL, json=payload) as resp:
                        saved = resp.status == 200
                        if not saved:
                            logger.warning(f"n8n logging failed: HTTP {resp.status} {await resp.text()}")
            except Exception as e:
                logger.warning(f"n8n logging failed: {e}")
        logger.info(f"Unanswered question logged={saved}: {question}")
        await params.result_callback({"recorded": saved})

    if AI_PROVIDER == "gemini":
        from pipecat.services.google.gemini_live.llm import GeminiLiveLLMService
        from pipecat.transcriptions.language import Language

        # Gemini Live hears, thinks and speaks in one model, with its own
        # server-side turn detection, so no separate STT/TTS/VAD is needed.
        gemini_settings = {
            "system_instruction": SYSTEM_PROMPT,
            "voice": os.getenv("GEMINI_VOICE", "Aoede"),
            "language": Language.AR,
        }
        if os.getenv("GEMINI_MODEL"):
            gemini_settings["model"] = os.environ["GEMINI_MODEL"]
        llm = GeminiLiveLLMService(
            api_key=GOOGLE_API_KEY,
            settings=GeminiLiveLLMService.Settings(**gemini_settings),
            tools=[log_unanswered_question],
        )

        context = LLMContext()
        user_aggregator, assistant_aggregator = LLMContextAggregatorPair(context)
        pipeline = Pipeline(
            [
                transport.input(),  # your microphone audio
                user_aggregator,  # collect what you said
                llm,  # Gemini Live: listens, thinks and speaks
                transport.output(),  # bot audio back to the browser
                assistant_aggregator,  # remember what the bot said
            ]
        )
        pipeline_params = PipelineParams(enable_metrics=True, enable_usage_metrics=True)
    else:
        from pipecat.audio.vad.silero import SileroVADAnalyzer
        from pipecat.services.openai.llm import OpenAILLMService
        from pipecat.services.openai.stt import OpenAIRealtimeSTTService
        from pipecat.services.openai.tts import OpenAITTSService

        # 1. Speech-to-text: understands what you say
        stt = OpenAIRealtimeSTTService(api_key=OPENAI_API_KEY)
        # 2. LLM: thinks up the reply (smaller model = faster replies; override with LLM_MODEL)
        llm = OpenAILLMService(
            api_key=OPENAI_API_KEY,
            settings=OpenAILLMService.Settings(
                model=os.getenv("LLM_MODEL", "gpt-4.1-mini"),
                system_instruction=SYSTEM_PROMPT,
            ),
        )
        # 3. Text-to-speech: speaks the reply
        tts = OpenAITTSService(
            api_key=OPENAI_API_KEY,
            settings=OpenAITTSService.Settings(voice="ballad"),
        )

        context = LLMContext(tools=[log_unanswered_question])
        user_aggregator, assistant_aggregator = LLMContextAggregatorPair(
            context,
            user_params=LLMUserAggregatorParams(vad_analyzer=SileroVADAnalyzer()),
        )
        pipeline = Pipeline(
            [
                transport.input(),  # your microphone audio
                stt,  # speech -> text
                user_aggregator,  # collect what you said
                llm,  # text -> reply
                tts,  # reply -> speech
                transport.output(),  # bot audio back to the browser
                assistant_aggregator,  # remember what the bot said
            ]
        )
        pipeline_params = PipelineParams(
            audio_out_sample_rate=24000,
            enable_metrics=True,
            enable_usage_metrics=True,
        )

    worker = PipelineWorker(
        pipeline,
        params=pipeline_params,
        idle_timeout_secs=runner_args.pipeline_idle_timeout_secs,
        processor_unusable_policy=ProcessorUnusablePolicy.END,
    )

    runner = WorkerRunner(handle_sigint=runner_args.handle_sigint)
    await runner.add_workers(worker)

    @transport.event_handler("on_client_connected")
    async def on_client_connected(transport, client):
        logger.info("Browser connected")
        context.add_message(
            {
                "role": "developer",
                "content": "Greet the caller in Jordanian Arabic as Raghad Organics customer service and ask how you can help, in one short sentence.",
            }
        )
        await worker.queue_frames([LLMRunFrame()])

    @transport.event_handler("on_client_disconnected")
    async def on_client_disconnected(transport, client):
        logger.info("Browser disconnected")
        await runner.cancel()

    await runner.run()


async def bot(runner_args: RunnerArguments):
    """Main bot entry point used by the Pipecat runner."""
    transport = await create_transport(runner_args, transport_params)
    await run_bot(transport, runner_args)


def mount_raghad_ui():
    """Serve the branded Raghad Organics page at /raghad/ and make it the home page.

    The stock Pipecat page stays available at /client/ as a fallback, and the
    WebRTC endpoint (/api/offer) is untouched, so both pages talk to the same bot.
    """
    from fastapi.responses import RedirectResponse
    from fastapi.staticfiles import StaticFiles

    from pipecat.runner.run import app

    ui_dir = os.path.join(os.path.dirname(os.path.abspath(__file__)), "raghad_ui")
    if not os.path.isdir(ui_dir):
        logger.warning(f"Branded UI folder not found ({ui_dir}); using the default /client/ page.")
        return

    # Registered before the runner's own "/" route, so this one wins.
    @app.get("/", include_in_schema=False)
    async def home():
        return RedirectResponse(url="/raghad/")

    @app.get("/raghad", include_in_schema=False)
    async def raghad_no_slash():
        return RedirectResponse(url="/raghad/")

    app.mount("/raghad", StaticFiles(directory=ui_dir, html=True), name="raghad_ui")
    logger.info("Raghad Organics UI mounted at /raghad/  (original UI: /client/)")


def add_deploy_routes():
    """Routes and protection needed when the bot runs on a public server (Railway).

    - /healthz: lets Railway check the service is up.
    - /raghad-config: hands the TURN/STUN servers (PIPECAT_ICE_SERVERS) to the
      browser page, so both sides of the call use the same relay.
    - SITE_PASSWORD (optional, off by default): if set, the whole site asks for a
      username/password (username "raghad", or SITE_USER). Leave it unset to let
      anyone with the link try the demo.
    """
    import base64
    import secrets

    from fastapi import Request
    from fastapi.responses import JSONResponse, Response

    from pipecat.runner.run import app

    @app.get("/healthz", include_in_schema=False)
    async def healthz():
        return {"status": "ok"}

    @app.get("/raghad-config", include_in_schema=False)
    async def raghad_config():
        raw = os.getenv("PIPECAT_ICE_SERVERS")
        ice_servers = []
        if raw:
            try:
                from pipecat.runner.run import _parse_ice_servers

                ice_servers = _parse_ice_servers(raw)
            except Exception as e:
                logger.error(f"Could not read PIPECAT_ICE_SERVERS: {e}")
        return JSONResponse({"iceServers": ice_servers}, headers={"Cache-Control": "no-store"})

    password = os.getenv("SITE_PASSWORD", "").strip()
    if not password:
        logger.info("Public mode: no SITE_PASSWORD set, anyone with the link can use this bot.")
        return

    username = os.getenv("SITE_USER", "raghad").strip() or "raghad"
    expected = "Basic " + base64.b64encode(f"{username}:{password}".encode()).decode()
    open_paths = {"/healthz"}

    @app.middleware("http")
    async def require_password(request: Request, call_next):
        if request.url.path in open_paths:
            return await call_next(request)
        given = request.headers.get("authorization", "")
        if secrets.compare_digest(given.encode(), expected.encode()):
            return await call_next(request)
        return Response(
            status_code=401,
            headers={"WWW-Authenticate": 'Basic realm="Raghad Organics demo", charset="UTF-8"'},
        )

    logger.info(f"Password protection is on (username: {username}).")


if __name__ == "__main__":
    from pipecat.runner.run import main

    add_deploy_routes()
    mount_raghad_ui()
    main()
