"""Static smoke checks for FraudLens dashboard source assets."""

import re
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DASHBOARD = ROOT / "fraudlens" / "dashboard"
SRC = DASHBOARD / "src"


class FrontendAssetSmokeTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = (SRC / "App.jsx").read_text(encoding="utf-8")
        cls.data = (SRC / "data" / "FraudLensData.jsx").read_text(encoding="utf-8")
        cls.cases = (SRC / "pages" / "CasesPage.jsx").read_text(encoding="utf-8")
        cls.graph = (SRC / "components" / "InvestGraph.jsx").read_text(encoding="utf-8")
        cls.actions = (SRC / "components" / "ActionsPanel.jsx").read_text(encoding="utf-8")
        cls.requests = (SRC / "components" / "EvidenceRequests.jsx").read_text(encoding="utf-8")
        cls.sar = (SRC / "components" / "SarDraft.jsx").read_text(encoding="utf-8")
        cls.timeline = (SRC / "components" / "CaseTimeline.jsx").read_text(encoding="utf-8")
        cls.styles = (SRC / "styles.css").read_text(encoding="utf-8")
        cls.index = (DASHBOARD / "index.html").read_text(encoding="utf-8")
        cls.vite = (DASHBOARD / "vite.config.js").read_text(encoding="utf-8")

    def test_stable_routes_and_lazy_analytics(self):
        self.assertIn("const AnalyticsView = lazy", self.app)
        self.assertNotIn("import AnalyticsView from", self.app)
        self.assertIn('path="/cases/:caseId"', self.app)
        self.assertIn('path="/analytics"', self.app)
        self.assertIn("<Navigate to=\"/cases\" replace />", self.app)
        self.assertIn("preview:", self.vite)
        self.assertIn("'/api': 'http://127.0.0.1:8000'", self.vite)

    def test_shared_data_context_deduplicates_requests(self):
        self.assertIn("const inFlightRequests = new Map()", self.data)
        self.assertIn("inFlightRequests.has(key)", self.data)
        self.assertIn("requestResource(key, loader, force)", self.data)
        self.assertIn("useDeviceNeighborhood", self.data)

    def test_queue_search_and_filters_are_labeled_and_url_backed(self):
        self.assertIn("useSearchParams", self.cases)
        self.assertIn('name="case-search"', self.cases)
        self.assertIn('htmlFor="verdict-filter"', self.cases)
        self.assertIn('htmlFor="risk-filter"', self.cases)
        self.assertIn('htmlFor="status-filter"', self.cases)
        self.assertIn('htmlFor="sar-filter"', self.cases)
        self.assertIn("No cases match these filters", self.cases)

    def test_graph_has_explicit_scope_and_no_orphan_edges(self):
        self.assertIn("addNode(nodeById, nodes", self.graph)
        self.assertIn("edge.from", self.graph)
        self.assertIn("edge.to", self.graph)
        self.assertIn("visibleIds.has(edge.from) && visibleIds.has(edge.to)", self.graph)
        self.assertIn("Show +", self.graph)
        self.assertIn("Table View", self.graph)
        self.assertIn("entities are", self.graph)
        self.assertIn("Device traversal", self.graph)

    def test_truthful_record_boundaries_are_visible(self):
        combined = f"{self.actions}\n{self.requests}\n{self.sar}\n{self.timeline}"
        self.assertIn("not supplied", combined)
        self.assertIn("Simulated", combined)
        self.assertIn("filing status is not confirmed", combined)
        self.assertIn("no timestamp", self.timeline)
        self.assertIn("Approval state:", self.actions)

    def test_mobile_and_accessibility_basics(self):
        self.assertIn('className="skip-link"', self.app)
        self.assertIn("aria-controls=\"primary-navigation\"", self.app)
        self.assertIn("aria-expanded={navOpen}", self.app)
        self.assertIn("closeNavigation", self.app)
        self.assertIn(":focus-visible", self.styles)
        self.assertIn("prefers-reduced-motion", self.styles)
        self.assertNotRegex(self.styles, r"transition\s*:\s*all")
        self.assertNotRegex(self.styles, r"outline\s*:\s*none")
        self.assertNotIn("maximum-scale=1", self.index)
        self.assertNotIn("user-scalable=no", self.index)

    def test_removed_legacy_components_are_not_referenced(self):
        for name in ("Queue.jsx", "CaseDetail.jsx", "RingView.jsx"):
            self.assertFalse((SRC / "components" / name).exists(), name)

        source_files = list(SRC.rglob("*.js")) + list(SRC.rglob("*.jsx"))
        source = "\n".join(path.read_text(encoding="utf-8") for path in source_files)
        for name in ("Queue", "CaseDetail", "RingView"):
            self.assertNotRegex(
                source,
                rf"from\s+['\"][^'\"]*{name}(?:\.jsx)?['\"]",
            )

    def test_no_unsafe_html_sink_or_zoom_lock(self):
        source_files = list(SRC.rglob("*.js")) + list(SRC.rglob("*.jsx"))
        source = "\n".join(path.read_text(encoding="utf-8") for path in source_files)
        self.assertNotIn("dangerouslySetInnerHTML", source)
        self.assertNotRegex(source, r"\.innerHTML\s*=")
        self.assertIsNone(re.search(r"<button[^>]*>\s*</button>", source, flags=re.IGNORECASE))


if __name__ == "__main__":
    unittest.main()
