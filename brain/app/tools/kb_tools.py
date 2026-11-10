from typing import Dict, Any, Optional, List
from app.agents.knowledge_agent import knowledge_agent
from app.rag.retriever import retriever
from app.services.menu_repo import menu_repo


def kb_ask(question: str, session: Optional[Any] = None) -> Dict[str, Any]:
    """
    Asks a question against the verified knowledge base (RAG).
    Returns grounded answer and source chunk IDs.
    """
    result = knowledge_agent.ask(question=question, session=session)
    return {
        "ok": True,
        "data": result
    }


def kb_search(query: str, k: int = 4, role: str = "customer") -> Dict[str, Any]:
    """
    Hybrid (vector + BM25) search with reranking and the relevance gate, restricted
    to the folders the role may see. Returns chunk ids, titles and scores only.
    """
    hits = retriever.retrieve(query=query, k=k, role=role)
    return {
        "ok": True,
        "data": {
            "hits": [
                {"id": h.id, "title": h.meta.get("title"), "folder": h.meta.get("folder"), "score": h.score}
                for h in hits
            ]
        }
    }


def menu_get_item(item_id: str) -> Dict[str, Any]:
    """
    Returns exact structured item details including current prices in integer LKR.
    """
    item = menu_repo.get_item(item_id)
    if not item:
        combo = menu_repo.get_combo(item_id)
        if combo:
            return {
                "ok": True,
                "data": combo.model_dump()
            }
        return {
            "ok": False,
            "error": "ITEM_NOT_FOUND",
            "message": f"Item '{item_id}' not found on menu."
        }

    return {
        "ok": True,
        "data": item.model_dump()
    }


def menu_list_items(
    category: Optional[str] = None,
    veg: Optional[bool] = None
) -> Dict[str, Any]:
    """
    Lists menu items filtered optionally by category or vegetarian status.
    """
    items = menu_repo.list_items(category=category, veg_only=veg)
    return {
        "ok": True,
        "data": {
            "items": [item.model_dump() for item in items]
        }
    }

