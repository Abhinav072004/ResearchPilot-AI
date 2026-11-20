"""Use Playwright with Chromium to verify the disposable React-to-worker workflow."""

import argparse
from secrets import token_hex

from playwright.sync_api import expect, sync_playwright


def smoke(origin, executable):
    with sync_playwright() as tools:
        browser = tools.chromium.launch(executable_path=executable)
        page = browser.new_page()
        page.set_default_timeout(20000)
        page.goto(origin, wait_until="networkidle")
        page.get_by_role("button", name="Create an account").click()
        page.get_by_label("Email").fill(f"browser-{token_hex(6)}@example.test")
        page.get_by_label("Password").fill("synthetic browser-only password")
        page.get_by_role("button", name="Create account", exact=True).click()
        page.locator("main").get_by_role("button", name="New project").click()
        page.get_by_label("Project title").fill("Synthetic browser flow")
        page.get_by_role("button", name="Create project").click()
        page.get_by_role("button", name="Library", exact=True).click()
        page.get_by_label("Paper title").fill("Synthetic optics")
        passage = "Synthetic albedo is defined as the fraction of incoming radiation reflected by a surface."
        page.get_by_label("Paper file").set_input_files({
            "name": "fixture.xml", "mimeType": "application/xml",
            "buffer": f"<article><body><p>{passage}</p></body></article>".encode(),
        })
        page.get_by_label("I have permission to process this paper").check()
        page.get_by_role("button", name="Upload paper").click()
        expect(page.get_by_text("Ingestion succeeded")).to_be_visible()
        page.get_by_role("button", name="Research", exact=True).click()
        page.get_by_role("textbox", name="Research question", exact=True).fill("What is albedo?")
        page.get_by_role("button", name="Run research").click()
        expect(page.get_by_text(passage)).to_be_visible()
        page.reload(wait_until="networkidle")
        page.get_by_role("button", name="What is albedo?", exact=True).click()
        expect(page.get_by_text(passage)).to_be_visible()
        page.get_by_role("button", name="[1] Synthetic optics · Document").click()
        inspector = page.get_by_role("complementary", name="Evidence inspector")
        expect(inspector.get_by_text(passage)).to_be_visible()
        page.get_by_role("button", name="Close evidence").click()
        page.get_by_role("button", name="Generate report").click()
        expect(page.get_by_text("Report succeeded")).to_be_visible()
        with page.expect_download() as download:
            page.get_by_role("link", name="PDF", exact=True).click()
        assert download.value.suggested_filename == "research-report.pdf"
        page.set_viewport_size({"width": 390, "height": 844})
        page.get_by_role("button", name="Toggle menu").click()
        page.get_by_role("button", name="New question").click()
        expect(page.get_by_role("heading", name="What are you researching?")).to_be_visible()
        page.get_by_role("button", name="Find a published source").click()
        assert "10.1371/journal.pmed.1000097" in page.get_by_role("textbox", name="Research question", exact=True).input_value()
        expect(page.get_by_label("Search literature")).to_be_checked()
        assert page.evaluate("document.documentElement.scrollWidth <= window.innerWidth")
        browser.close()
    print("Browser smoke passed signup, ingestion, saved research, citations, report export and mobile navigation.")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("origin")
    parser.add_argument("--chromium", default=None, help="Use a system Chromium executable")
    args = parser.parse_args()
    smoke(args.origin, args.chromium)
