import json
import logging
import uuid
from pathlib import Path
from typing import Any, Dict, List, Optional
from app.config import settings
from app.schemas import BrainReply, BrainReplyMeta, IncomingMessage
from app.state.session import Session, get_session_store
from app.services.language import detect_language
from app.services.post_processor import verify_and_post_process_reply
from app.services.branch_repo import branch_repo
from app.services import pricing
from app.tools.registry import registry
from app.llm.client import llm_client
from app.agents.knowledge_agent import knowledge_agent

log = logging.getLogger("brain.orchestrator")

PROMPT_VERSION = "orchestrator_v1"
PROMPT_FILE = settings.PROMPTS_DIR / f"{PROMPT_VERSION}.md"


def load_system_prompt() -> str:
    if PROMPT_FILE.exists():
        return PROMPT_FILE.read_text(encoding="utf-8")
    return "You are the official Pizza Hut WhatsApp ordering assistant."


class Orchestrator:
    def __init__(self):
        self.prompt_template = load_system_prompt()

    def _build_state_block(self, session: Session) -> str:
        cart_desc = "empty"
        if session.cart:
            sub = pricing.subtotal(session.cart)
            cart_desc = f"{len(session.cart)} item(s), food subtotal LKR {sub:,}"

        open_statuses = []
        for b in branch_repo.list_branches():
            is_open = branch_repo.is_open(b.id, mode=session.fulfilment or "delivery")
            status_word = "OPEN" if is_open else "CLOSED"
            open_statuses.append(f"{b.id}:{status_word}")

        lines = [
            "=== CURRENT SESSION STATE ===",
            f"Stage: {session.stage}",
            f"Fulfilment: {session.fulfilment or 'not_set'}",
            f"Branch: {session.branch_id or 'not_set'}",
            f"Delivery Zone: {session.delivery_zone or 'not_set'}",
            f"Address: {session.address or 'not_set'}",
            f"Promo: {session.promo_code or 'none'}",
            f"Cart: {cart_desc}",
            f"Summary Hash: {session.summary_hash or 'none'}",
            f"Branch Hours: {', '.join(open_statuses)}",
            f"Language: {session.language or 'en'}",
            "=============================",
        ]
        return "\n".join(lines)

    async def handle_message(self, msg: IncomingMessage) -> BrainReply:
        trace_id = str(uuid.uuid4())[:8]
        store = get_session_store()
        user_id = msg.user_id

        # 1. Acquire per-user lock
        async with store.lock(user_id):
            # 2. Check deduplication
            if msg.message_id and await store.is_duplicate_message(user_id, msg.message_id):
                cached = await store.get_cached_reply(user_id, msg.message_id)
                if cached:
                    log.info("[%s] Duplicate message_id=%s served from cache", trace_id, msg.message_id)
                    return cached

            # 3. Check rate limiting (e.g. 20 msgs/min)
            allowed, _ = await store.check_rate_limit(user_id)
            if not allowed:
                return BrainReply(
                    reply_text="You're sending messages a bit too fast! Please wait a moment and try again 🙏",
                    meta=BrainReplyMeta(stage="browsing", trace_id=trace_id),
                )

            # 4. Load session
            session = await store.get(user_id)

            # If user already placed an order on the last turn, start fresh for new conversation
            if session.stage == "placed":
                session.reset_cart()

            # 5. Cheap pre-checks
            raw_text = (msg.content or "").strip()

            # Handle location message type
            if msg.type == "location" and msg.location:
                raw_text = f"My location is lat: {msg.location.lat}, lng: {msg.location.lng}"

            if not raw_text and msg.type != "location":
                reply = BrainReply(
                    reply_text="Hello! Welcome to Pizza Hut! How can I help you today? 🍕",
                    meta=BrainReplyMeta(stage=session.stage, branch_id=session.branch_id, trace_id=trace_id),
                )
                return reply

            # Detect language
            session.language = detect_language(raw_text)

            # 6. Build prompt context
            state_block = self._build_state_block(session)
            system_prompt = f"{self.prompt_template}\n\n{state_block}"

            conversation_msgs: List[Dict[str, Any]] = []
            for h in session.history[-12:]:
                conversation_msgs.append({"role": h["role"], "content": h["content"]})
            conversation_msgs.append({"role": "user", "content": raw_text})

            session.message_count += 1
            executed_tools: List[Dict[str, Any]] = []
            reply_text = ""

            # 7. Tool loop (up to MAX_TOOL_ITERATIONS)
            iteration = 0
            while iteration < settings.MAX_TOOL_ITERATIONS:
                iteration += 1
                available_tools = registry.tools_for_stage(session.stage)

                try:
                    llm_resp = llm_client.complete(
                        system=system_prompt,
                        messages=conversation_msgs,
                        model=settings.ORCHESTRATOR_MODEL,
                        tools=available_tools if available_tools else None,
                        temperature=0.1,
                    )
                except Exception as e:
                    log.warning("[%s] Orchestrator LLM completion failed (%s). Executing fallback.", trace_id, e)
                    # Safe fallback: if user is asking questions, route to knowledge agent
                    rag_res = knowledge_agent.ask(raw_text, session=session)
                    reply_text = rag_res.get("answer", "I'm having a little trouble connecting right now. Please try again in a minute 🙏")
                    break

                if not llm_resp.tool_calls:
                    reply_text = llm_resp.text.strip()
                    break

                # Execute tool calls
                # Append assistant tool call message to chain
                conversation_msgs.append({
                    "role": "assistant",
                    "content": llm_resp.text,
                    "tool_calls": [
                        {
                            "id": tc["id"],
                            "type": "function",
                            "function": {
                                "name": tc["function"]["name"],
                                "arguments": tc["function"]["arguments"],
                            },
                        }
                        for tc in llm_resp.tool_calls
                    ],
                })

                for tc in llm_resp.tool_calls:
                    fn_name = tc["function"]["name"]
                    try:
                        fn_args = json.loads(tc["function"]["arguments"]) if tc["function"]["arguments"] else {}
                    except Exception:
                        fn_args = {}

                    tool_res = registry.call(fn_name, session=session, args=fn_args)
                    executed_tools.append(tool_res)

                    conversation_msgs.append({
                        "role": "tool",
                        "tool_call_id": tc["id"],
                        "name": fn_name,
                        "content": json.dumps(tool_res, ensure_ascii=False),
                    })

                # Refresh state block if tools mutated session
                system_prompt = f"{self.prompt_template}\n\n{self._build_state_block(session)}"

            if not reply_text and iteration >= settings.MAX_TOOL_ITERATIONS:
                reply_text = "I'm working on your request. Let me connect you with one of our staff members to assist you directly 🙏"

            # 8. Post-process reply (price integrity & formatting)
            processed_text = verify_and_post_process_reply(reply_text, session, executed_tools)

            # 9. Update history & save session
            session.add_history("user", raw_text)
            session.add_history("assistant", processed_text)
            await store.save(session)

            reply = BrainReply(
                reply_text=processed_text,
                meta=BrainReplyMeta(
                    stage=session.stage,
                    branch_id=session.branch_id,
                    trace_id=trace_id,
                ),
            )

            # 10. Record dedupe
            if msg.message_id:
                await store.record_message_reply(user_id, msg.message_id, reply)

            log.info(
                "[%s] user=%s stage=%s branch=%s tools=%d len=%d",
                trace_id,
                user_id,
                session.stage,
                session.branch_id,
                len(executed_tools),
                len(processed_text),
            )
            return reply


orchestrator = Orchestrator()
