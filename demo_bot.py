#
# Pipecat voice demo - OpenAI only (speech-to-text, LLM and text-to-speech).
# Based on examples/voice/voice-openai.py, trimmed to the browser (WebRTC)
# transport so it needs no Daily / LiveKit / Deepgram / Cartesia accounts.
#
# Run from the repo root:   uv run demo_bot.py -t webrtc
# Then open:                http://localhost:7860/  (branded page; stock page at /client/)
#

import os

from dotenv import load_dotenv
from loguru import logger

from pipecat.audio.vad.silero import SileroVADAnalyzer
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
from pipecat.services.openai.llm import OpenAILLMService
from pipecat.services.openai.stt import OpenAIRealtimeSTTService
from pipecat.services.openai.tts import OpenAITTSService
from pipecat.transports.base_transport import BaseTransport, TransportParams
from pipecat.workers.runner import WorkerRunner

load_dotenv(override=True)

if not os.getenv("OPENAI_API_KEY"):
    raise SystemExit("OPENAI_API_KEY is missing. Put it in the .env file next to this script.")

# Only the browser (WebRTC) transport, so no extra accounts are needed.
transport_params = {
    "webrtc": lambda: TransportParams(
        audio_in_enabled=True,
        audio_out_enabled=True,
    ),
}

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
    "Answer ONLY from the knowledge base below. If the answer is not there, say you are not sure "
    "and give the customer service number 06 222 2700. Never invent prices, policies or medical advice.\n\n"
    "=== KNOWLEDGE BASE ===\n" + KNOWLEDGE
)


async def run_bot(transport: BaseTransport, runner_args: RunnerArguments):
    logger.info("Starting demo bot")
    api_key = os.environ["OPENAI_API_KEY"]

    # 1. Speech-to-text: understands what you say
    stt = OpenAIRealtimeSTTService(api_key=api_key)

    # 2. LLM: thinks up the reply
    llm = OpenAILLMService(
        api_key=api_key,
        settings=OpenAILLMService.Settings(system_instruction=SYSTEM_PROMPT),
    )

    # 3. Text-to-speech: speaks the reply
    tts = OpenAITTSService(
        api_key=api_key,
        settings=OpenAITTSService.Settings(voice="ballad"),
    )

    context = LLMContext()
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

    worker = PipelineWorker(
        pipeline,
        params=PipelineParams(
            audio_out_sample_rate=24000,
            enable_metrics=True,
            enable_usage_metrics=True,
        ),
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
    - DEMO_PASSWORD: if set, the whole site asks for a username/password
      (username "raghad", or DEMO_USER) so strangers can't spend your OpenAI credit.
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

    password = os.getenv("DEMO_PASSWORD", "").strip()
    if not password:
        logger.warning("DEMO_PASSWORD is not set: anyone with the link can use this bot.")
        return

    username = os.getenv("DEMO_USER", "raghad").strip() or "raghad"
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
