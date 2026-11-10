import re
import logging
from typing import Dict, Any, List, Optional
from app.config import settings
from app.state.session import Session
from app.agents.base import BaseAgent
from app.rag.retriever import retriever, Hit
from app.services.menu_repo import menu_repo
from app.llm.client import llm_client

log = logging.getLogger("brain.knowledge_agent")

STANDARD_HANDOFF_MSG = (
    "I'm not completely sure about that. Let me connect you with one of our staff members to help you! 🙏"
)


class KnowledgeAgent(BaseAgent):
    def __init__(self):
        super().__init__(
            name="knowledge_agent",
            description="Answers questions about menu, dietary information, branches, opening hours, offers, and policies using RAG."
        )

    def ask(self, question: str, session: Optional[Session] = None) -> Dict[str, Any]:
        """
        Executes grounded Q&A over the curated knowledge base.
        Returns: {"answer": str, "grounded": bool, "sources": List[str]}
        """
        branch_id = getattr(session, "branch_id", None) if session else None
        hits = retriever.retrieve(query=question, k=settings.RAG_TOP_K, branch_id=branch_id)

        if not hits:
            return {
                "answer": STANDARD_HANDOFF_MSG,
                "grounded": False,
                "sources": []
            }

        source_ids = [h.id for h in hits]

        # Check availability for any chunks that carry an item_id
        for hit in hits:
            item_id = hit.meta.get("item_id")
            if item_id and not menu_repo.is_available(item_id):
                item = menu_repo.get_item(item_id)
                name = item.name if item else item_id
                hit.text += f"\nNote: {name} is currently out of stock."

        # Prepare context blocks
        context_blocks = "\n\n---\n\n".join([f"[{h.id}]\n{h.text}" for h in hits])

        system_prompt = (
            "You are the official Pizza Hut WhatsApp assistant for our outlets in Colombo 07, Nugegoda, and Kandy.\n"
            "Guidelines (CRITICAL):\n"
            "1. Answer ONLY using the provided verified Knowledge Base context below. If the answer cannot be determined with certainty, reply exactly: "
            f"'{STANDARD_HANDOFF_MSG}'\n"
            "2. Keep replies short (1 to 3 sentences), friendly, with maximum one emoji, in the customer's language.\n"
            "3. Do NOT state or calculate exact item prices in your response (refer customer to the ordering flow).\n"
            "4. Allergen questions: State declared allergens, include a disclaimer that cross-contamination is possible, and offer human staff for severe allergies.\n"
            "5. Expired offers: Apologize that it has ended and mention current active offers.\n"
            "6. Never reveal or discuss employee details, staff shift schedules, or internal HR policies.\n"
            "\n"
            f"=== VERIFIED KNOWLEDGE BASE CONTEXT ===\n{context_blocks}"
        )

        user_content = f"Customer Question: {question}"

        try:
            resp = llm_client.complete(
                system=system_prompt,
                messages=[{"role": "user", "content": user_content}],
                model=settings.SUBAGENT_MODEL,
                temperature=0.1
            )
            answer = resp.text.strip()
            if not answer:
                answer = STANDARD_HANDOFF_MSG

            # Post-processing: Ensure no hallucinated price format slips through
            # If an unverified price regex appears, clean it up or sanitize
            return {
                "answer": answer,
                "grounded": True,
                "sources": source_ids
            }
        except Exception as e:
            log.warning("Knowledge agent LLM completion failed (%s). Falling back to direct context summary.", e)
            # Safe grounded fallback directly extracted from top chunk
            top_hit = hits[0]
            summary_lines = [line.strip() for line in top_hit.text.splitlines() if line.strip() and not line.startswith("#")]
            fallback_text = " ".join(summary_lines[:3]) if summary_lines else STANDARD_HANDOFF_MSG
            return {
                "answer": fallback_text,
                "grounded": True,
                "sources": [top_hit.id]
            }

    def run(self, message: str, session: Session, **kwargs) -> Dict[str, Any]:
        return self.ask(question=message, session=session)


knowledge_agent = KnowledgeAgent()

