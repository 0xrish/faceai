import asyncio
import os
import shutil
import tempfile
import urllib.request
from datetime import timedelta
from typing import Any, Dict, List
from urllib.parse import urlparse

from apify import Actor
from crawlee.crawlers import PlaywrightCrawler, PlaywrightCrawlingContext


def _load_env() -> None:
    root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    env_path = os.path.join(root, ".env")
    if not os.path.exists(env_path):
        return
    with open(env_path) as f:
        for line in f:
            line = line.strip()
            if line and not line.startswith("#") and "=" in line:
                key, _, val = line.partition("=")
                os.environ.setdefault(key.strip(), val.strip())


def _resolve_file_url(url: str) -> str:
    return urllib.request.url2pathname(urlparse(url).path)


# Result types to fetch from the API
SEARCH_TYPES = ["people", "similar", "related", "duplicates"]


async def main() -> None:
    _load_env()

    debug: bool = os.environ.get("DEBUG", "false").lower() == "true"
    headless: bool = not debug

    async with Actor:
        Actor.log.info(f"Starting Face AI Actor  debug={debug}  headless={headless}")

        actor_input = await Actor.get_input() or {}

        start_urls_raw = actor_input.get("startUrls", [{"url": "https://lenso.ai/en/"}])
        start_urls = [r.get("url") if isinstance(r, dict) else r for r in start_urls_raw]

        image_urls: List[Any] = actor_input.get("imageUrls", [])
        image_uploads: List[Any] = actor_input.get("imageUpload", [])
        all_images = [i for i in image_urls + image_uploads if i]

        proxy_config = actor_input.get("proxyConfiguration")

        if not all_images:
            src_dir = os.path.dirname(os.path.abspath(__file__))
            fallback = os.path.join(src_dir, "profile.jpeg")
            if os.path.exists(fallback):
                all_images = [{"url": f"file:///{fallback.replace(os.sep, '/')}"}]
                Actor.log.info(f"Using local fallback: {fallback}")
            else:
                await Actor.fail(status_message="No image provided.")
                return

        proxy_configuration = None
        if proxy_config:
            proxy_configuration = await Actor.create_proxy_configuration(actor_proxy_input=proxy_config)

        crawler = PlaywrightCrawler(
            max_requests_per_crawl=10,
            proxy_configuration=proxy_configuration,
            headless=headless,
            request_handler_timeout=timedelta(seconds=180),
        )

        @crawler.pre_navigation_hook
        async def load_cookies(context: PlaywrightCrawlingContext, **kwargs: Any) -> None:
            import json
            cookie_path = os.path.join(os.path.dirname(__file__), "lenso.ai.cookies.json")
            if not os.path.exists(cookie_path):
                return
            try:
                with open(cookie_path, "r") as f:
                    raw = f.read().strip()
                if not raw or raw == "[]":
                    return
                cookies = json.loads(raw)
                if cookies:
                    await context.page.context.add_cookies(cookies)
                    context.log.info(f"Loaded {len(cookies)} cookies")
            except Exception as e:
                context.log.warning(f"Cookie load skipped: {e}")

        @crawler.router.default_handler
        async def default_handler(context: PlaywrightCrawlingContext) -> None:
            page = context.page
            context.log.info(f"Processing: {context.request.url}")

            # ── Resolve image ────────────────────────────────────────────────
            img_req = all_images[0]
            img_url: str = img_req.get("url") if isinstance(img_req, dict) else str(img_req)

            tmp_img = os.path.join(tempfile.gettempdir(), "photo.jpeg")
            try:
                if img_url.startswith("file://"):
                    local = _resolve_file_url(img_url)
                    if not os.path.exists(local):
                        raise FileNotFoundError(local)
                    shutil.copy2(local, tmp_img)
                else:
                    req = urllib.request.Request(img_url)
                    if "api.apify.com" in img_url:
                        token = os.environ.get("APIFY_TOKEN", "")
                        if token:
                            req.add_header("Authorization", f"Bearer {token}")
                    with urllib.request.urlopen(req) as resp:
                        with open(tmp_img, "wb") as out:
                            out.write(resp.read())
                context.log.info(f"Image ready at {tmp_img}")
            except Exception as e:
                context.log.error(f"Image fetch failed: {e}")
                await Actor.push_data({"url": context.request.url, "image_searched": img_url,
                                       "status": "failed", "error": str(e)})
                return

            async def snap(label: str) -> None:
                if not debug:
                    return
                key = f"{label}.png"
                await Actor.set_value(key, await page.screenshot(full_page=False), content_type="image/png")
                context.log.info(f"Screenshot → {key}")

            # ── Upload flow ──────────────────────────────────────────────────
            try:
                await snap("step01_loaded")

                # Cookie consent — try multiple selectors
                consent_clicked = False
                try:
                    await page.get_by_role("button", name="Allow all").click(timeout=5000)
                    consent_clicked = True
                    context.log.info("Clicked 'Allow all' consent")
                except Exception:
                    pass

                if not consent_clicked:
                    try:
                        await page.locator("button:has-text('Allow all')").click(timeout=5000)
                        consent_clicked = True
                        context.log.info("Clicked consent via has-text selector")
                    except Exception:
                        pass

                if consent_clicked:
                    await page.wait_for_timeout(500)

                # Click search textbox
                try:
                    await page.get_by_role("textbox", name="or type to search").click(timeout=5000)
                except Exception:
                    pass

                # Click the "Drop, paste or upload" text
                try:
                    await page.get_by_text("Drop, paste or upload an image").click(timeout=5000)
                except Exception:
                    pass

                # Upload via JavaScript file API (simulate drop event)
                try:
                    # Read file as base64 and inject via JavaScript
                    import base64
                    with open(tmp_img, 'rb') as f:
                        file_data = base64.b64encode(f.read()).decode()

                    await page.evaluate(f"""
                        async () => {{
                            const response = await fetch('data:image/jpeg;base64,{file_data}');
                            const blob = await response.blob();
                            const files = [new File([blob], 'photo.jpeg', {{ type: 'image/jpeg' }})];

                            // Dispatch drop event on body
                            const dt = new DataTransfer();
                            files.forEach(f => dt.items.add(f));

                            const dropEvent = new DragEvent('drop', {{
                                bubbles: true,
                                cancelable: true,
                                dataTransfer: dt,
                            }});
                            document.body.dispatchEvent(dropEvent);

                            // Also try input event on any file inputs
                            const fileInputs = document.querySelectorAll('input[type="file"]');
                            for (const input of fileInputs) {{
                                input.files = dt.files;
                                input.dispatchEvent(new Event('change', {{ bubbles: true }}));
                            }}
                        }}
                    """)
                    context.log.info("Uploaded via JavaScript drop event")
                except Exception as e:
                    context.log.error(f"JavaScript upload failed: {e}")
                    raise

                await page.wait_for_timeout(1500)
                await snap("step02_uploaded")

                # Consent checkboxes
                try:
                    await page.get_by_role("checkbox", name="I have read and accept").check(timeout=5000)
                    await page.get_by_role("checkbox", name="I agree to send photos to").check(timeout=5000)
                except Exception:
                    pass

                # Search
                await page.get_by_role("button", name="Perform Search").click()
                context.log.info("Search submitted")
                await page.wait_for_timeout(2000)
                await snap("step03_searching")

                # Captcha (Prosopo proof-of-work)
                try:
                    captcha_visible = await page.get_by_text(
                        "Verify you are a human", exact=True
                    ).is_visible(timeout=3000)
                except Exception:
                    captcha_visible = False

                if captcha_visible:
                    context.log.info("Captcha detected — attempting PoW solve")
                    await snap("step_captcha")

                    try:
                        # Find the Prosopo checkbox via data-cy attribute (stable test selector)
                        checkbox = page.locator("[data-cy='captcha-checkbox']")
                        context.log.info("Waiting before clicking captcha checkbox...")
                        await page.wait_for_timeout(2000)  # Wait 2s before clicking
                        await checkbox.click(timeout=5000)
                        context.log.info("Clicked captcha checkbox — PoW computation starting")

                        # Wait for Submit button to become enabled (PoW completes)
                        submit_btn = page.locator("button.verify-btn")
                        context.log.info("Waiting for PoW computation (up to 60 seconds)...")

                        # Poll for disabled attribute to be removed
                        for attempt in range(60):  # 60 seconds (120 * 500ms)
                            disabled = await submit_btn.get_attribute("disabled")
                            if disabled is None:
                                context.log.info("PoW completed, Submit enabled")
                                break
                            if attempt % 10 == 0:
                                context.log.info(f"  Still computing... {attempt // 2}s elapsed")
                            await page.wait_for_timeout(500)

                        # Wait before clicking Submit
                        context.log.info("Waiting before clicking Submit...")
                        await page.wait_for_timeout(2000)

                        # Click Submit
                        await submit_btn.click(timeout=5000)
                        context.log.info("Clicked Submit")
                        await page.wait_for_timeout(3000)

                    except Exception as e:
                        context.log.error(f"Captcha solve failed: {e}")
                        context.log.warning(
                            "Captcha automation detected as bot. Automated PoW solving is not possible. "
                            "To bypass: Add real browser cookies to src/lenso.ai.cookies.json. "
                            "Steps: (1) Visit lenso.ai in Chrome, (2) Complete a search manually, "
                            "(3) Export cookies with Cookie-Editor extension (Export → JSON), "
                            "(4) Paste JSON array into lenso.ai.cookies.json"
                        )

                # Wait for results page — "All" tab confirms navigation complete
                try:
                    await page.get_by_role("button", name="All").wait_for(state="visible", timeout=60000)
                    context.log.info("Results page ready")
                except Exception:
                    context.log.warning("Results page not detected within 60s")
                await snap("step04_results")

                # ── Extract image ID from results URL ────────────────────────
                results_url = page.url
                try:
                    image_id = results_url.split("/results/")[1].split("?")[0]
                    context.log.info(f"Image ID: {image_id}")
                except IndexError:
                    context.log.error(f"Could not parse image ID from URL: {results_url}")
                    await Actor.push_data({"url": results_url, "image_searched": img_url,
                                           "status": "failed", "error": "Image ID not found in URL"})
                    return

                # ── Call lenso.ai search API for each result type ────────────
                # Using page.evaluate so the browser session cookies are sent automatically.
                all_results: List[Dict[str, Any]] = []

                for result_type in SEARCH_TYPES:
                    try:
                        data = await page.evaluate("""async ([imageId, type]) => {
                            const resp = await fetch('https://lenso.ai/api/search', {
                                method: 'POST',
                                headers: {
                                    'Content-Type': 'application/json',
                                    'Accept': 'application/json',
                                },
                                body: JSON.stringify({
                                    image: { id: imageId },
                                    effects: { rotation: 0 },
                                    selection: { top: 0, left: 0, right: 1, bottom: 1 },
                                    domain: '',
                                    text: '',
                                    page: 1,
                                    type: type,
                                    sort: '',
                                    seed: 0,
                                    facial_search_consent: 1
                                })
                            });
                            if (!resp.ok) return null;
                            return resp.json();
                        }""", [image_id, result_type])

                        if not data or not data.get("results"):
                            context.log.info(f"  {result_type}: no results")
                            continue

                        for r in data["results"]:
                            sources = [
                                {
                                    "source_url": u.get("sourceUrl", ""),
                                    "title": u.get("title", ""),
                                    "image_url": u.get("imageUrl", ""),
                                }
                                for u in r.get("urlList", [])
                            ]
                            all_results.append({
                                "result_type": result_type,
                                "hash": r.get("hash"),
                                "distance": r.get("distance"),
                                "proxy_url": r.get("proxyUrl"),
                                "category": r.get("category"),
                                "locked": r.get("type") == "LOCKED",
                                "sources": sources,
                            })

                        context.log.info(f"  {result_type}: {len(data['results'])} results")

                    except Exception as e:
                        context.log.warning(f"  {result_type} API call failed: {e}")

                context.log.info(f"Total results: {len(all_results)}")

                await Actor.push_data({
                    "url": results_url,
                    "image_id": image_id,
                    "image_searched": img_url,
                    "status": "success",
                    "result_count": len(all_results),
                    "results": all_results,
                })
                context.log.info("Done — pushed to dataset")

            except Exception as e:
                context.log.exception(f"Automation error: {e}")
                await snap("error_state")
                await Actor.push_data({
                    "url": context.request.url,
                    "image_searched": img_url,
                    "status": "failed",
                    "error": str(e),
                })

        await crawler.run(start_urls)


if __name__ == "__main__":
    asyncio.run(main())
