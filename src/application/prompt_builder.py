"""Builds LLM messages keeping instructions (system) and data (documents) separated.

Documents are XML-escaped so their content cannot close the ``<document>`` or
``<untrusted_documents>`` tags and "escape" into the instruction channel.
"""

from html import escape

from domain.models.document import GuardedDocument
from ports.llm import Message


class PromptBuilder:
    def __init__(self, system_prompt: str) -> None:
        self._system_prompt = system_prompt

    def planning_messages(self, query: str) -> list[Message]:
        return [
            {"role": "system", "content": self._system_prompt},
            {"role": "user", "content": query},
        ]

    def answer_messages(self, query: str, documents: list[GuardedDocument]) -> list[Message]:
        blocks = "\n".join(
            f'<document id="{escape(d.document.id)}" title="{escape(d.document.title)}">\n'
            f"{escape(d.safe_text, quote=False)}\n"
            f"</document>"
            for d in documents
        )
        user_content = (
            f"<user_query>\n{escape(query, quote=False)}\n</user_query>\n\n"
            f"<untrusted_documents>\n{blocks}\n</untrusted_documents>\n\n"
            "Answer the user query using only the documents above and cite their IDs."
        )
        return [
            {"role": "system", "content": self._system_prompt},
            {"role": "user", "content": user_content},
        ]
