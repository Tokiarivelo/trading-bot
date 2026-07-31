#!/usr/bin/env python3
"""
🎬 Automated Video Tour Generator for AI Trading Bot
Uses Playwright to conduct a smooth, human-like video tour of the entire frontend platform
and saves the walkthrough as an MP4 video suitable for Facebook & LinkedIn advertising.

Prerequisites:
    pip install playwright
    playwright install chromium
    (Optional, for MP4 conversion) ffmpeg installed in your system PATH

Usage:
    1. Ensure frontend dev server is running (http://localhost:3000): `make dev-frontend`
    2. Run this script: `python3 scripts/record_demo_tour.py`
"""

import os
import time
import subprocess
from pathlib import Path

try:
    from playwright.sync_api import sync_playwright, TimeoutError as PlaywrightTimeout
except ImportError:
    print("❌ Playwright is not installed. Run: pip install playwright && playwright install chromium")
    exit(1)

FRONTEND_URL = os.environ.get("FRONTEND_URL", "http://localhost:3001")
OUTPUT_DIR = Path("./videos/demo_tour")


def simulate_human_pause(page, seconds: float = 2.0):
    """Pause execution smoothly while allowing browser animations to continue."""
    page.wait_for_timeout(int(seconds * 1000))


def smooth_scroll(page, distance: int = 500, steps: int = 20):
    """Perform smooth vertical scrolling on the active page."""
    step_distance = distance // steps
    for _ in range(steps):
        page.mouse.wheel(0, step_distance)
        page.wait_for_timeout(50)
    simulate_human_pause(page, 1.5)
    # Scroll back up slightly
    for _ in range(steps // 2):
        page.mouse.wheel(0, -step_distance)
        page.wait_for_timeout(40)
    simulate_human_pause(page, 1.0)


def run_demo_tour():
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    print(f"🎬 Starting Playwright Video Tour Recording against {FRONTEND_URL}...")

    with sync_playwright() as p:
        # Launch Chromium with smooth speed (slow_mo) for better video comprehension
        browser = p.chromium.launch(
            headless=True,  # Set to True for reliable headless recording in terminal
            slow_mo=200,
            args=["--window-size=1920,1080"]
        )
        
        # Configure Full-HD video recording
        context = browser.new_context(
            viewport={"width": 1920, "height": 1080},
            record_video_dir=str(OUTPUT_DIR),
            record_video_size={"width": 1920, "height": 1080},
            color_scheme="dark"
        )

        page = context.new_page()

        try:
            # ---------------------------------------------------------
            # SCENE 1: MAIN DASHBOARD & TRADINGVIEW CHART (00:00 - 00:15)
            # ---------------------------------------------------------
            print("📍 Scene 1: Exploring Main Dashboard & TradingView Chart...")
            page.goto(FRONTEND_URL, wait_until="networkidle")
            simulate_human_pause(page, 3.0)

            # Move mouse across the chart area smoothly to highlight candlesticks/tooltips
            page.mouse.move(500, 400, steps=25)
            simulate_human_pause(page, 1.0)
            page.mouse.move(800, 350, steps=25)
            simulate_human_pause(page, 1.0)
            page.mouse.move(1100, 450, steps=25)
            simulate_human_pause(page, 2.0)

            # Try to click on timeframe buttons if available (e.g., M5, H1)
            for text in ["M5", "M15", "H1"]:
                btn = page.get_by_text(text, exact=True)
                if btn.count() > 0 and btn.first.is_visible():
                    btn.first.click()
                    simulate_human_pause(page, 2.0)

            # ---------------------------------------------------------
            # SCENE 2: AI STRATEGY GENERATION VIA PDF (00:15 - 00:30)
            # ---------------------------------------------------------
            print("📍 Scene 2: Navigating to AI Strategies & PDF Importer...")
            nav_strategy = page.get_by_text("Strategies", exact=False).first
            if nav_strategy.is_visible():
                nav_strategy.click()
            else:
                page.goto(f"{FRONTEND_URL}/strategies")
            
            page.wait_for_load_state("domcontentloaded")
            simulate_human_pause(page, 3.0)
            smooth_scroll(page, distance=600)

            # ---------------------------------------------------------
            # SCENE 3: AI SELF-REFINEMENT REPORTS (00:30 - 00:45)
            # ---------------------------------------------------------
            print("📍 Scene 3: Checking AI Self-Refinement (10-Trade Cycle) Reports...")
            page.goto(f"{FRONTEND_URL}/ai-reports")
            page.wait_for_load_state("domcontentloaded")
            simulate_human_pause(page, 3.0)
            smooth_scroll(page, distance=500)

            # ---------------------------------------------------------
            # SCENE 4: BOTS & MULTI-ACCOUNT MANAGER (00:45 - 00:58)
            # ---------------------------------------------------------
            print("📍 Scene 4: Touring Bots & Account Management...")
            page.goto(f"{FRONTEND_URL}/bots")
            page.wait_for_load_state("domcontentloaded")
            simulate_human_pause(page, 3.0)

            page.goto(f"{FRONTEND_URL}/bot-control")
            page.wait_for_load_state("domcontentloaded")
            simulate_human_pause(page, 3.0)
            smooth_scroll(page, distance=400)

            # ---------------------------------------------------------
            # SCENE 5: BACKTESTING ENGINE & ANALYTICS (00:58 - 01:12)
            # ---------------------------------------------------------
            print("📍 Scene 5: Checking Backtest Engine & Analytics...")
            page.goto(f"{FRONTEND_URL}/backtest")
            page.wait_for_load_state("domcontentloaded")
            simulate_human_pause(page, 3.0)

            page.goto(f"{FRONTEND_URL}/analytics")
            page.wait_for_load_state("domcontentloaded")
            simulate_human_pause(page, 3.0)
            smooth_scroll(page, distance=600)

            # ---------------------------------------------------------
            # SCENE 6: NEWS CIRCUIT BREAKERS & SETTINGS (01:12 - 01:25)
            # ---------------------------------------------------------
            print("📍 Scene 6: Economic Calendar News & Safety Settings...")
            page.goto(f"{FRONTEND_URL}/news")
            page.wait_for_load_state("domcontentloaded")
            simulate_human_pause(page, 3.0)
            smooth_scroll(page, distance=400)

            page.goto(f"{FRONTEND_URL}/settings")
            page.wait_for_load_state("domcontentloaded")
            simulate_human_pause(page, 3.0)
            smooth_scroll(page, distance=500)

            # ---------------------------------------------------------
            # SCENE 7: RETURN TO MAIN CHART FOR OUTRO (01:25 - 01:30)
            # ---------------------------------------------------------
            print("📍 Scene 7: Return to Dashboard for Outro...")
            page.goto(FRONTEND_URL)
            simulate_human_pause(page, 4.0)
            
            print("✅ Walkthrough tour successfully completed in browser.")

        except Exception as e:
            print(f"⚠️ Error during tour execution: {e}")
        finally:
            # Closing context triggers saving of the recorded video
            page.close()
            context.close()
            browser.close()

    # Find the recorded WebM file
    recorded_files = list(OUTPUT_DIR.glob("*.webm"))
    if not recorded_files:
        print("❌ No video files found in output directory.")
        return

    latest_video = max(recorded_files, key=os.path.getmtime)
    print(f"🎥 Raw HD video saved at: {latest_video}")

    # Attempt conversion to MP4 via FFmpeg for optimal Facebook/LinkedIn playback
    target_mp4 = OUTPUT_DIR / "AI_Trading_Bot_Platform_Walkthrough_90s.mp4"
    try:
        print(f"🔄 Converting {latest_video.name} to MP4 for Ads compatibility...")
        cmd = [
            "ffmpeg", "-y", "-i", str(latest_video),
            "-c:v", "libx264", "-preset", "slow", "-crf", "18",
            "-c:a", "aac", str(target_mp4)
        ]
        subprocess.run(cmd, check=True, stdout=subprocess.DEVNULL, stderr=subprocess.STDOUT)
        print(f"✨ SUCCESS! MP4 Video ready for Facebook & LinkedIn Ads: {target_mp4}")
        # Optionally remove the webm file after successful conversion
        # latest_video.unlink()
    except (subprocess.CalledProcessError, FileNotFoundError):
        print("💡 Note: 'ffmpeg' was not found or failed to convert to MP4.")
        print(f"👉 Your video is available as standard WebM at: {latest_video}")


if __name__ == "__main__":
    run_demo_tour()
