#!/usr/bin/env python3
"""
🎬 Automated XAUUSD Chart Features & Right-Side Tools LONG Video Tour (French Subtitles)
Uses Playwright to record an in-depth, leisurely video (3 to 4 minutes) focusing strictly on Gold (XAUUSD).
Deactivates Volume histogram, Trade labels, Trade arrows, and Period separators while keeping ONLY Order lines active.
Exhaustively clicks, pauses, and interactively demonstrates technical indicators, multi-timeframe switching,
session replays, manual paper trade execution, the right-hand side bot management panel (with the Bot Eye signal toggle),
and interactive clicks on Active Orders & Trade History table rows to illuminate trade trajectories on the chart.
"""

import os
import time
import urllib.request
import subprocess
from pathlib import Path

try:
    from playwright.sync_api import sync_playwright, TimeoutError as PlaywrightTimeout
except ImportError:
    print("❌ Playwright is not installed. Run: pip install playwright && playwright install chromium")
    exit(1)


def get_default_url():
    for port in [3000, 3001, 3002]:
        try:
            url = f"http://localhost:{port}"
            with urllib.request.urlopen(url, timeout=1):
                return url
        except Exception:
            continue
    return "http://localhost:3000"


FRONTEND_URL = os.environ.get("FRONTEND_URL", get_default_url())
OUTPUT_DIR = Path("./videos/demo_tour")


def simulate_human_pause(page, seconds: float = 3.0):
    """Pause execution smoothly for several seconds so viewer can read subtitles and observe events."""
    page.wait_for_timeout(int(seconds * 1000))


def set_french_subtitle(page, text: str):
    """Injects or updates a sleek, glassmorphic floating subtitle overlay in French on the video screen."""
    page.evaluate(
        """(subtitleText) => {
        let overlay = document.getElementById('ai-trading-bot-subtitle');
        if (!overlay) {
            overlay = document.createElement('div');
            overlay.id = 'ai-trading-bot-subtitle';
            overlay.style.position = 'fixed';
            overlay.style.bottom = '35px';
            overlay.style.left = '50%';
            overlay.style.transform = 'translateX(-50%)';
            overlay.style.zIndex = '999999';
            overlay.style.backgroundColor = 'rgba(15, 23, 42, 0.95)';
            overlay.style.color = '#ffffff';
            overlay.style.padding = '16px 36px';
            overlay.style.borderRadius = '50px';
            overlay.style.boxShadow = '0 12px 30px rgba(0,0,0,0.7), 0 0 20px rgba(234,179,8,0.4)';
            overlay.style.border = '1px solid rgba(234, 179, 8, 0.6)';
            overlay.style.fontFamily = 'Inter, -apple-system, sans-serif';
            overlay.style.fontSize = '22px';
            overlay.style.fontWeight = '600';
            overlay.style.textAlign = 'center';
            overlay.style.letterSpacing = '0.4px';
            overlay.style.maxWidth = '85%';
            overlay.style.transition = 'all 0.5s cubic-bezier(0.16, 1, 0.3, 1)';
            overlay.style.pointerEvents = 'none';
            document.body.appendChild(overlay);
        }
        overlay.style.opacity = '0';
        overlay.style.transform = 'translate(-50%, 12px)';
        setTimeout(() => {
            overlay.innerHTML = subtitleText;
            overlay.style.opacity = '1';
            overlay.style.transform = 'translate(-50%, 0)';
        }, 250);
    }""",
        text,
    )
    simulate_human_pause(page, 2.5)


def safe_click(page, selector_or_locator, name: str = "", wait_after: float = 3.0):
    """Clicks an element reliably and waits long enough for visual animations and UI state changes."""
    try:
        if isinstance(selector_or_locator, str):
            loc = page.locator(selector_or_locator).first
        else:
            loc = selector_or_locator
        loc.scroll_into_view_if_needed(timeout=2000)
        if loc.is_visible(timeout=3000):
            loc.hover()
            page.wait_for_timeout(500)
            loc.click(force=True)
            print(f"   👉 Successfully clicked on '{name}'")
            simulate_human_pause(page, wait_after)
            return True
        else:
            print(f"   ⚠️ Element '{name}' not visible after waiting.")
    except Exception as e:
        print(f"   💡 Notice: Element '{name}' click attempt had exception: {e}")
    return False


def configure_chart_overlays(page):
    """
    Deactivates Volume histogram, Trade labels, Trade arrows, and Period separators.
    Ensures ONLY 'Order lines' is activated. Uses deliberate pauses between each click.
    """
    print("📍 Configuring Chart Overlays: Deactivating Volume/Labels/Arrows/Separators, activating ONLY Order lines...")
    overlay_btn = page.locator("button[title*='Chart overlay settings']").first
    if not overlay_btn.is_visible(timeout=3000):
        print("   ⚠️ Overlay settings gear button not visible.")
        return
    
    overlay_btn.hover()
    overlay_btn.click()
    simulate_human_pause(page, 2.5)

    forbidden_labels = [
        "Volume histogram",
        "Trade labels (BUY/SELL)",
        "Trade arrows (BUY/SELL)",
        "Period separators",
    ]
    for label in forbidden_labels:
        try:
            item = page.locator(f"button:has-text('{label}'), div:has-text('{label}') button").first
            if item.is_visible():
                html = item.inner_html()
                # Check if it has an active Check icon or Eye icon
                if "lucide-check" in html or "text-accent" in html or "lucide-eye " in html:
                    item.hover()
                    page.wait_for_timeout(400)
                    item.click()
                    print(f"   👉 Deactivated overlay: {label}")
                    simulate_human_pause(page, 2.0)
        except Exception as e:
            print(f"   Notice checking {label}: {e}")

    # Activate ONLY Order lines
    try:
        order_item = page.locator("div:has(span:text-is('Order lines')) button, button:has-text('Order lines')").first
        if order_item.is_visible():
            html = order_item.inner_html()
            if "lucide-check" not in html and "text-accent" not in html:
                order_item.hover()
                page.wait_for_timeout(400)
                order_item.click()
                print("   👉 Activated ONLY Order lines overlay")
                simulate_human_pause(page, 2.5)
            else:
                print("   ✔ Order lines overlay is already active.")
    except Exception as e:
        print(f"   Notice checking Order lines: {e}")

    # Close overlay settings dropdown cleanly
    page.keyboard.press("Escape")
    simulate_human_pause(page, 2.0)


def run_long_chart_features_tour():
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    print(f"🎬 Starting Playwright LONG XAUUSD Chart Features Video Tour against {FRONTEND_URL}...")

    with sync_playwright() as p:
        browser = p.chromium.launch(
            headless=True,  # Set False if running locally on a GUI Desktop to watch live
            slow_mo=250,
            args=["--window-size=1920,1080"],
        )
        context = browser.new_context(
            viewport={"width": 1920, "height": 1080},
            record_video_dir=str(OUTPUT_DIR),
            record_video_size={"width": 1920, "height": 1080},
            color_scheme="dark",
        )
        page = context.new_page()

        try:
            # ---------------------------------------------------------
            # SCENE 1: FOCUS EXCLUSIF XAUUSD & CONFIGURATION OVERLAYS (~30s)
            # ---------------------------------------------------------
            print("📍 Scene 1: Exclusive XAUUSD Focus & Strict Overlay Configuration...")
            page.goto(FRONTEND_URL, wait_until="networkidle", timeout=15000)
            simulate_human_pause(page, 3.5)

            # Ensure XAUUSD chip is selected; DO NOT ADD or switch to other symbols!
            xau_chip = page.get_by_text("XAUUSD", exact=True).first
            if xau_chip.is_visible():
                xau_chip.hover()
                xau_chip.click()
                print("   👉 Selected XAUUSD Symbol")
                simulate_human_pause(page, 2.5)

            set_french_subtitle(
                page,
                "✨ <b>Focus Exclusif Or (XAUUSD) & Filtrage Strict</b> : Activation unique des Lignes d'Ordres pour une clarté absolue.",
            )
            configure_chart_overlays(page)

            # Glide mouse slowly across candlesticks
            page.mouse.move(600, 400, steps=35)
            simulate_human_pause(page, 2.0)
            page.mouse.move(900, 450, steps=30)
            simulate_human_pause(page, 2.5)

            # ---------------------------------------------------------
            # SCENE 2: TIMEFRAME EXPLORATION ON XAUUSD (~35s)
            # ---------------------------------------------------------
            print("📍 Scene 2: Detailed Timeframe Exploration (M1, M5, M15, H1, D1)...")
            set_french_subtitle(
                page,
                "⏱️ <b>Navigation Multi-Unités de Temps</b> : Observez l'adaptation instantanée des bougies du micro-scalping (M1/M5) aux grandes tendances (H1/D1).",
            )
            for tf in ["M1", "M5", "M15", "H1", "D1", "M5"]:
                btn = page.locator(f"button:has-text('{tf}'), span:text-is('{tf}')").first
                if btn.is_visible():
                    btn.hover()
                    btn.click()
                    print(f"   👉 Clicked timeframe {tf}")
                    # Long wait so viewer clearly observes the candlestick regeneration on XAUUSD!
                    simulate_human_pause(page, 4.5)

            # ---------------------------------------------------------
            # SCENE 3: INDICATORS DOCK DEEP DIVE (~35s)
            # ---------------------------------------------------------
            print("📍 Scene 3: Technical Indicators Dock & Customization...")
            set_french_subtitle(
                page,
                "📊 <b>Suite d'Indicateurs Techniques</b> : Ouvrez le panneau, activez vos indicateurs favoris (EMA, RSI, MACD) et paramétrez-les en direct.",
            )
            ind_btn = page.locator("button[title*='technical indicators'], button[title*='Add or configure']").first
            safe_click(page, ind_btn, "Indicators Button", wait_after=4.0)

            # Interact with an indicator inside the newly opened dock if available
            ind_item = page.locator("button:has-text('EMA'), button:has-text('RSI'), button:has-text('Bollinger'), .indicator-row button").first
            if ind_item.is_visible():
                ind_item.hover()
                simulate_human_pause(page, 1.0)
                safe_click(page, ind_item, "Toggle Indicator", wait_after=5.0)
            
            # Allow ample time to inspect indicators on the chart before closing the dock
            simulate_human_pause(page, 4.0)
            safe_click(page, ind_btn, "Close Indicators Dock", wait_after=3.0)

            # ---------------------------------------------------------
            # SCENE 4: SESSION REPLAY ENGINE (~35s)
            # ---------------------------------------------------------
            print("📍 Scene 4: Session Replay Engine Bar-by-Bar...")
            set_french_subtitle(
                page,
                "⏪ <b>Moteur Replay Historique</b> : Sélectionnez une session passée sur le XAUUSD et rejouez le marché barre par barre pour entraîner votre stratégie !",
            )
            replay_btn = page.locator("button[title*='Replay an arbitrary historical period'], button[title*='Replay'], button:has-text('Replay')").first
            if safe_click(page, replay_btn, "Session Replay Button", wait_after=4.5):
                # Try to interact with replay picker controls (Play, Start, or Date selector)
                play_btn = page.locator("button[title*='Play'], button:has-text('Start'), button:has(svg.lucide-play)").first
                if play_btn.is_visible():
                    safe_click(page, play_btn, "Start Replay Play", wait_after=6.0)
                else:
                    simulate_human_pause(page, 5.0)
                
                # Exit replay picker by hitting escape or re-clicking button
                page.keyboard.press("Escape")
                simulate_human_pause(page, 3.0)

            # ---------------------------------------------------------
            # SCENE 5: RIGHT SIDE OF CHART - BOTS MANAGEMENT & THE EYE TOGGLE (~45s)
            # ---------------------------------------------------------
            print("📍 Scene 5: Right Side of Chart - Bots Management & Eye Signal Toggle...")
            set_french_subtitle(
                page,
                "👁️ <b>Panneau Latéral & Vision IA (Le Bouton Œil)</b> : Activez l'icône Œil pour projeter sur le graphique la logique secrète et les signaux en direct de vos robots !",
            )
            # Glide mouse across right side panels (Account status & Bot Selector)
            page.mouse.move(1550, 280, steps=30)
            simulate_human_pause(page, 2.5)

            # If there is an 'Activate on XAUUSD' button because no bots are running yet, click it!
            activate_bot_btn = page.locator("button:has-text('Activate on XAUUSD'), button:has-text('Activate on')").first
            if activate_bot_btn.is_visible():
                safe_click(page, activate_bot_btn, "Activate Bot on XAUUSD", wait_after=6.0)

            # Now find and CLICK the Bot Eye button (title contains Show/Hide signal history or svg.lucide-eye)
            eye_btn = page.locator("button[title*='signals'], button[title*='Show'], button[title*='Hide'], button:has(svg.lucide-eye), button:has(svg.lucide-eye-off)").first
            if safe_click(page, eye_btn, "Bot Eye Signal Toggle Button", wait_after=8.0):
                print("   👉 Bot eye signals successfully projected on XAUUSD chart!")
                # Move mouse back over the chart to admire the signal overlay trail
                page.mouse.move(850, 450, steps=35)
                simulate_human_pause(page, 5.0)

            # ---------------------------------------------------------
            # SCENE 6: MANUAL TRADE EXECUTION IN TRADE PANEL (~35s)
            # ---------------------------------------------------------
            print("📍 Scene 6: Manual Trade Execution (Buy/Sell on XAUUSD)...")
            set_french_subtitle(
                page,
                "⚡ <b>Exécution Directe & Trade Panel</b> : Placez vos ordres d'achat ou de vente en un clic en Mode Simulation 100% sécurisé !",
            )
            # Find Buy or Sell market buttons in TradePanel on the right
            buy_btn = page.locator("button:has-text('Buy'), button:text-is('Buy'), button[title*='Buy']").first
            if safe_click(page, buy_btn, "Market Buy Order on XAUUSD", wait_after=6.0):
                print("   👉 Successfully opened simulated BUY position on XAUUSD!")
            else:
                sell_btn = page.locator("button:has-text('Sell'), button:text-is('Sell')").first
                safe_click(page, sell_btn, "Market Sell Order on XAUUSD", wait_after=6.0)
            
            simulate_human_pause(page, 4.0)

            # ---------------------------------------------------------
            # SCENE 7: ACTIVE ORDERS & HISTORY - INTERACTIVE ROW CLICKING (~50s)
            # ---------------------------------------------------------
            print("📍 Scene 7: Orders Dock - Clicking Active Orders & History Rows to Highlight on Chart...")
            set_french_subtitle(
                page,
                "📑 <b>Ordres Actifs & Historique Interactif</b> : Cliquez directement sur vos positions ou sur l'historique pour illuminer la trajectoire du trade sur le graphique !",
            )
            # Open the OrdersDock if it is currently hidden by clicking the bottom-right 'Orders' button!
            active_tab_check = page.locator("button:has-text('Active orders')").first
            if not active_tab_check.is_visible(timeout=1500):
                orders_toggle = page.locator("button[title*='Show / hide active orders'], button:text-is('Orders'), button:has-text('Orders')").first
                safe_click(page, orders_toggle, "Orders Dock Expand Button", wait_after=3.5)

            # Ensure we click the 'Active orders' tab
            active_tab = page.locator("button:has-text('Active orders'), button:has-text('Active')").first
            safe_click(page, active_tab, "Active Orders Tab", wait_after=3.5)

            # Click on an order row / position in the table!
            # Clicking a table row triggers handleSelectOrderTicket, dimming background and highlighting the trade line!
            active_row = page.locator("table tbody tr, tr[title*='Highlight']").first
            if safe_click(page, active_row, "Active Position Table Row", wait_after=8.0):
                print("   👉 Position line highlighted in glowing accent color on chart!")
                page.keyboard.press("Escape")
                simulate_human_pause(page, 2.5)

            # Switch to 'History' tab
            history_tab = page.locator("button:has-text('History')").first
            safe_click(page, history_tab, "Trade History Tab", wait_after=4.5)

            # Click on a closed trade row in History to project historical markers on chart!
            history_row = page.locator("table tbody tr, tr[title*='Highlight']").first
            if safe_click(page, history_row, "Historical Trade Table Row", wait_after=8.0):
                print("   👉 Historical trade markers shown directly on XAUUSD chart!")
                page.keyboard.press("Escape")
                simulate_human_pause(page, 3.0)

            # ---------------------------------------------------------
            # SCENE 8: OUTRO & CONCLUSION (~25s)
            # ---------------------------------------------------------
            print("📍 Scene 8: Final Panoramic Zoom on XAUUSD & Outro...")
            set_french_subtitle(
                page,
                "🚀 <b>Relevez le niveau de votre trading sur le XAUUSD avec notre moteur IA quantitatif</b>. Connectez votre terminal dès aujourd'hui !",
            )
            page.mouse.move(800, 420, steps=40)
            simulate_human_pause(page, 6.0)

            print("✅ LONG XAUUSD chart functionalities video tour successfully completed in browser.")

        except Exception as e:
            print(f"⚠️ Error during long chart features recording: {e}")
        finally:
            page.close()
            context.close()
            browser.close()

    # Locate recorded WebM
    recorded_files = list(OUTPUT_DIR.glob("*.webm"))
    if not recorded_files:
        print("❌ No video files found in output directory.")
        return

    latest_video = max(recorded_files, key=os.path.getmtime)
    print(f"🎥 Raw HD XAUUSD long chart feature recording saved at: {latest_video}")

    target_mp4 = OUTPUT_DIR / "AI_Trading_Bot_Chart_Features_FR.mp4"
    try:
        print(f"🔄 Converting {latest_video.name} to French-subtitled MP4...")
        cmd = [
            "ffmpeg",
            "-y",
            "-i",
            str(latest_video),
            "-c:v",
            "libx264",
            "-preset",
            "slow",
            "-crf",
            "18",
            "-c:a",
            "aac",
            str(target_mp4),
        ]
        subprocess.run(cmd, check=True, stdout=subprocess.DEVNULL, stderr=subprocess.STDOUT)
        print(f"✨ SUCCESS! French XAUUSD LONG Chart Features MP4 Video ready: {target_mp4}")
    except (subprocess.CalledProcessError, FileNotFoundError):
        print("💡 Note: 'ffmpeg' conversion failed or not present. Raw WebM available above.")


if __name__ == "__main__":
    run_long_chart_features_tour()
