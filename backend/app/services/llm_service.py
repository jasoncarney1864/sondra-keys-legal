"""
LLM service for generating Q&A responses using Azure OpenAI.
Implements the Sondra persona for accessible legal document explanations.
"""

import logging
from typing import Optional
from openai import AsyncAzureOpenAI

from backend.app.core.config import settings

logger = logging.getLogger(__name__)


# ============================================================================
# SONDRA SYSTEM PROMPT - The Core of the Legal QA Persona
# ============================================================================
SONDRA_SYSTEM_PROMPT = """You are Sondra, an expert legal document assistant specializing in translating complex legal text into clear, accessible "plain English" explanations.

## Your Core Principles:
1. **Simplicity First**: Eliminate legalese. Replace "whereas," "heretofore," and archaic language with modern, everyday words.
2. **Accuracy**: Never sacrifice precision for simplicity. If a term is legally important, explain it in simple terms rather than omit it.
3. **Context Matters**: Acknowledge the specific document being discussed (e.g., "This lease agreement...").
4. **Empathy**: Remember the user is likely stressed or confused. Be warm, reassuring, and patient.
5. **Completeness**: Cover all relevant aspects of the question, including:
   - What it means
   - Why it matters
   - What it means for the user
   - Any common pitfalls or exceptions

## Answer Format:
- Start with a direct, one-sentence answer
- Follow with a detailed explanation (2-3 paragraphs)
- Highlight key implications for the user
- Offer next steps if appropriate

## Language Guidelines:
- Use "you" and "your" to make it personal
- Break complex ideas into short sentences
- Use analogies or examples when helpful
- Avoid Latin phrases (explain instead)
- Replace "party/parties" with "person/people" when possible
- Never start with "According to section X" - just explain it

## Example Transformation:
❌ BEFORE: "The lessor hereby covenants and agrees to maintain the demised premises in a state of good repair and condition..."
✅ AFTER: "The landlord must keep the apartment in good working condition. This means fixing problems with plumbing, walls, heating, and anything else that might break."

## When You Don't Know:
- Be honest: "I don't see this addressed in the document provided."
- Suggest they consult a real lawyer for complex legal questions
- Offer to search the document for related terms

You are a trusted ally in the document, not a substitute for professional legal counsel."""
# ============================================================================


class LLMService:
    """
    Generates Q&A responses using Azure OpenAI with the Sondra persona.
    Specializes in making legal documents accessible and understandable.
    """

    def __init__(self):
        """Initialize the LLM service with Azure OpenAI client."""
        self.client = AsyncAzureOpenAI(
            api_key=settings.ai.openai_api_key,
            api_version=settings.ai.openai_api_version,
            azure_endpoint=str(settings.ai.openai_endpoint),
        )
        self.deployment_name = settings.ai.openai_deployment_name
        self.model_name = "gpt-4"
        self.temperature = 0.7
        self.max_tokens = 1000

    async def answer_question(
        self,
        question: str,
        document_context: str,
        document_title: Optional[str] = None,
    ) -> str:
        """
        Generate a plain-English answer to a question about a legal document.

        Args:
            question: The user's question
            document_context: Relevant excerpts from the document
            document_title: Optional title of the document being discussed

        Returns:
            Plain-English answer from Sondra

        Raises:
            ValueError: If question or context is empty
            Exception: If Azure OpenAI API fails
        """
        if not question or not question.strip():
            raise ValueError("Question cannot be empty")
        if not document_context or not document_context.strip():
            raise ValueError("Document context cannot be empty")

        try:
            logger.info(f"Answering question: {question[:50]}...")

            # Build context prefix
            context_prefix = f"Document: {document_title}\n\n" if document_title else ""

            # Create the user message with document context
            user_message = f"""{context_prefix}Here's the relevant section from the document:

{document_context}

---

User Question: {question}

Please explain this in simple, plain English."""

            # Call Azure OpenAI
            response = await self.client.chat.completions.create(
                model=self.deployment_name,
                messages=[
                    {
                        "role": "system",
                        "content": SONDRA_SYSTEM_PROMPT,
                    },
                    {
                        "role": "user",
                        "content": user_message,
                    },
                ],
                temperature=self.temperature,
                max_tokens=self.max_tokens,
            )

            answer = response.choices[0].message.content
            logger.info(f"Generated answer ({len(answer)} characters)")
            return answer

        except Exception as e:
            logger.error(f"Failed to generate answer: {str(e)}")
            raise

    async def summarize_section(
        self,
        section_text: str,
        section_title: Optional[str] = None,
    ) -> str:
        """
        Generate a plain-English summary of a document section.

        Args:
            section_text: The section text to summarize
            section_title: Optional title of the section

        Returns:
            Plain-English summary

        Raises:
            ValueError: If section_text is empty
            Exception: If Azure OpenAI API fails
        """
        if not section_text or not section_text.strip():
            raise ValueError("Section text cannot be empty")

        try:
            logger.info(f"Summarizing section: {section_title or 'untitled'}")

            title_prefix = f"Section: {section_title}\n\n" if section_title else ""

            user_message = f"""{title_prefix}Please summarize this legal text in simple, plain English. Focus on what it means for someone reading it:

{section_text}

Provide a 2-3 sentence summary that explains:
1. What this section is about
2. What it means in everyday language
3. Why it matters"""

            response = await self.client.chat.completions.create(
                model=self.deployment_name,
                messages=[
                    {
                        "role": "system",
                        "content": SONDRA_SYSTEM_PROMPT,
                    },
                    {
                        "role": "user",
                        "content": user_message,
                    },
                ],
                temperature=self.temperature,
                max_tokens=300,
            )

            summary = response.choices[0].message.content
            logger.info(f"Generated summary ({len(summary)} characters)")
            return summary

        except Exception as e:
            logger.error(f"Failed to summarize section: {str(e)}")
            raise

    async def explain_term(self, term: str, context: Optional[str] = None) -> str:
        """
        Explain a legal term in plain English.

        Args:
            term: The legal term to explain
            context: Optional context where the term was found

        Returns:
            Plain-English explanation of the term

        Raises:
            ValueError: If term is empty
            Exception: If Azure OpenAI API fails
        """
        if not term or not term.strip():
            raise ValueError("Term cannot be empty")

        try:
            logger.info(f"Explaining term: {term}")

            context_suffix = (
                f"\n\nContext where it appeared: {context}" if context else ""
            )

            user_message = f"""Explain this legal term in simple, plain English:

Term: {term}{context_suffix}

Please provide:
1. A one-sentence simple definition
2. A short explanation (2-3 sentences) of what it means
3. A real-world example if relevant"""

            response = await self.client.chat.completions.create(
                model=self.deployment_name,
                messages=[
                    {
                        "role": "system",
                        "content": SONDRA_SYSTEM_PROMPT,
                    },
                    {
                        "role": "user",
                        "content": user_message,
                    },
                ],
                temperature=self.temperature,
                max_tokens=250,
            )

            explanation = response.choices[0].message.content
            logger.info(f"Generated explanation ({len(explanation)} characters)")
            return explanation

        except Exception as e:
            logger.error(f"Failed to explain term: {str(e)}")
            raise
