import unittest

from app.services.financial_chat import (
    ChatEntity,
    build_private_company_response,
    build_unknown_asset_response,
    dedupe_context_blocks,
    dedupe_response_sections,
    detect_language,
    infer_intent,
)


class FinancialChatSafetyTests(unittest.TestCase):
    def test_spacex_technical_analysis_private_company_response(self):
        entity = ChatEntity(
            raw="SpaceX",
            normalized="SpaceX",
            entity_type="private_company",
            confidence=0.99,
            proxies=["RKLB", "ASTS", "IRDM", "ARKX", "UFO"],
        )
        response = build_private_company_response("it", entity, technical_requested=True)
        text = response["composed_response"]
        self.assertIn("SpaceX non e quotata", text)
        self.assertIn("RKLB", text)
        self.assertNotIn("AMAT", text)
        self.assertNotIn("RSI 50", text)
        self.assertNotIn("MACD", response["standard_sections"][0]["bullets"][0])

    def test_openai_fundamental_analysis_private_company_response(self):
        entity = ChatEntity(raw="OpenAI", normalized="OpenAI", entity_type="private_company", confidence=0.99, proxies=["MSFT", "NVDA"])
        response = build_private_company_response("it", entity, fundamental_requested=True)
        text = response["composed_response"]
        self.assertIn("societa privata", text)
        self.assertIn("ticker pubblico", text)
        self.assertNotIn("P/E", text)

    def test_italian_language_detection(self):
        self.assertEqual(detect_language("Analisi tecnica di Nvidia"), "it")

    def test_english_language_detection(self):
        self.assertEqual(detect_language("Technical analysis of Nvidia"), "en")

    def test_nvidia_technical_intent(self):
        self.assertEqual(infer_intent("Analisi tecnica di Nvidia"), "technical_analysis")

    def test_full_analysis_intent(self):
        self.assertEqual(infer_intent("Analizza NVIDIA con approccio tecnico e fondamentale"), "full_analysis")

    def test_unknown_asset_safe_failure(self):
        entity = ChatEntity(raw="UnknownCo", normalized="UnknownCo", entity_type="unknown_asset", confidence=0.4)
        response = build_unknown_asset_response("it", entity)
        text = response["composed_response"]
        self.assertIn("Non riesco a collegare", text)
        self.assertNotIn("NVDA", text)
        self.assertNotIn("AMAT", text)

    def test_context_deduplication(self):
        rows = [{"ticker": "AMAT", "x": 1}, {"ticker": "AMAT", "x": 2}, {"ticker": "NVDA", "x": 3}]
        deduped = dedupe_context_blocks(rows)
        self.assertEqual([row["ticker"] for row in deduped], ["AMAT", "NVDA"])

    def test_response_section_deduplication(self):
        sections = [
            {"key": "summary", "title": "Summary", "bullets": ["A", "A"]},
            {"key": "summary", "title": "Summary duplicate", "bullets": ["B"]},
        ]
        deduped = dedupe_response_sections(sections)
        self.assertEqual(len(deduped), 1)
        self.assertEqual(deduped[0]["bullets"], ["A"])


if __name__ == "__main__":
    unittest.main()
