"""E2E smoke test for https://dubbing.zhangjiangnan.art.

Run from project root:
    python utils/scripts/e2e_smoke.py
Outputs screenshots to ./e2e_artifacts/ and prints a pass/fail table at the end.
"""

from __future__ import annotations

import json
import sys
import time
from dataclasses import dataclass, field
from pathlib import Path

from playwright.sync_api import (
    Page,
    TimeoutError as PWTimeout,
    sync_playwright,
)

BASE_URL = "https://dubbing.zhangjiangnan.art"
ARTIFACTS = Path(__file__).resolve().parents[2] / "e2e_artifacts"
ARTIFACTS.mkdir(exist_ok=True)


@dataclass
class StepResult:
    name: str
    passed: bool
    detail: str = ""
    screenshot: str = ""


@dataclass
class Report:
    steps: list[StepResult] = field(default_factory=list)

    def add(self, step: StepResult) -> None:
        self.steps.append(step)
        marker = "PASS" if step.passed else "FAIL"
        print(f"[{marker}] {step.name}  ({step.detail})  shot={step.screenshot}")

    def summary(self) -> str:
        lines = ["", "=" * 72, "RESULTS", "=" * 72]
        for s in self.steps:
            marker = "✅" if s.passed else "❌"
            lines.append(f"{marker} {s.name}")
            if s.detail:
                lines.append(f"     · {s.detail}")
            if s.screenshot:
                lines.append(f"     · {s.screenshot}")
        passed = sum(1 for s in self.steps if s.passed)
        lines.append("")
        lines.append(f"Total: {passed}/{len(self.steps)} passed")
        return "\n".join(lines)


def shot(page: Page, name: str) -> str:
    path = ARTIFACTS / f"{name}.png"
    page.screenshot(path=str(path), full_page=True)
    return str(path)


def wait_streamlit_idle(page: Page, timeout_ms: int = 30000) -> None:
    """Wait for Streamlit's running indicator to settle."""
    deadline = time.time() + timeout_ms / 1000.0
    while time.time() < deadline:
        try:
            running = page.locator('[data-testid="stStatusWidget"]').count()
            if running == 0:
                page.wait_for_load_state("networkidle", timeout=5000)
                return
        except Exception:
            pass
        time.sleep(0.3)


def fill_by_label(page: Page, label: str, value: str) -> None:
    """Streamlit text_input renders label above input; find input by label sibling."""
    # Streamlit pattern: label is in a div with data-testid="stWidgetLabel", input is sibling
    label_node = page.locator(f'label:has-text("{label}")').first
    label_node.wait_for(state="visible", timeout=10000)
    # The input is usually the next input element inside the same widget
    widget = label_node.locator("xpath=ancestor::div[@data-testid='stTextInput'][1]")
    if widget.count() == 0:
        widget = label_node.locator("xpath=ancestor::div[contains(@class,'stTextInput')][1]")
    widget.locator("input").fill(value)


def click_button(page: Page, label: str, exact: bool = True, nth: int = 0) -> None:
    btn = page.get_by_role("button", name=label, exact=exact).nth(nth)
    btn.wait_for(state="visible", timeout=10000)
    btn.click()


def login(page: Page, username: str, password: str, report: Report, tag: str) -> bool:
    page.goto(BASE_URL, wait_until="domcontentloaded")
    wait_streamlit_idle(page)
    s = shot(page, f"{tag}_01_login_page")

    # Step 1: confirm local login form (username field, not email)
    has_username = page.locator('label:has-text("用户名")').count() > 0
    has_email = page.locator('label:has-text("📧 邮箱")').count() > 0
    if has_username and not has_email:
        report.add(StepResult(f"{tag}-1: local login page shown (用户名/密码)", True,
                              "found 用户名 label, no email label", s))
    else:
        report.add(StepResult(f"{tag}-1: local login page shown", False,
                              f"用户名={has_username} 邮箱={has_email}", s))
        return False

    try:
        fill_by_label(page, "用户名", username)
        fill_by_label(page, "密码", password)
        click_button(page, "登录")
        wait_streamlit_idle(page)
        # success toast or rerun -> sidebar visible
        time.sleep(1.5)
        wait_streamlit_idle(page)
    except Exception as e:
        s = shot(page, f"{tag}_02_login_error")
        report.add(StepResult(f"{tag}-2: login as {username}", False, f"exception: {e}", s))
        return False

    s = shot(page, f"{tag}_02_after_login")
    # Heuristic: post-login the sidebar should have "📊 统计" or page shows "工程"
    logged_in = (
        page.locator('text=📊 统计').count() > 0
        or page.locator('text=工程管理').count() > 0
        or page.locator('text=创建新工程').count() > 0
        or page.locator('button:has-text("🔓 注销")').count() > 0
    )
    if logged_in:
        report.add(StepResult(f"{tag}-2: login as {username}", True, "main UI visible", s))
        return True
    else:
        # Maybe still showing error
        err_text = ""
        for sel in ['div[role="alert"]', '.stAlert', 'text=密码错误', 'text=用户名不存在']:
            loc = page.locator(sel)
            if loc.count() > 0:
                try:
                    err_text = loc.first.inner_text(timeout=1000)[:200]
                    break
                except Exception:
                    continue
        report.add(StepResult(f"{tag}-2: login as {username}", False,
                              f"no main UI; alert={err_text!r}", s))
        return False


def list_projects(page: Page) -> list[str]:
    """Return visible project name strings from project list cards."""
    # Project name renders as `#### 📁 {name}` -> h4 with the leading 📁
    names = []
    try:
        nodes = page.locator('h4:has-text("📁")').all()
        for n in nodes:
            try:
                txt = n.inner_text(timeout=1000)
                txt = txt.replace("📁", "").strip()
                if txt:
                    names.append(txt)
            except Exception:
                continue
    except Exception:
        pass
    return names


def open_project_by_name(page: Page, name: str) -> bool:
    """Click the '🚀 继续' button whose card contains the given project name."""
    # Find the card container that has this name, then click its 继续 button.
    # Each card is wrapped by an st.container; the h4 and 继续 button share a common parent.
    h4 = page.locator(f'h4:has-text("{name}")').first
    if h4.count() == 0:
        return False
    h4.wait_for(state="visible", timeout=5000)
    # Walk up to the nearest container with class containing 'stVerticalBlock', then find button inside.
    card = h4.locator("xpath=ancestor::div[contains(@class,'stVerticalBlock')][1]")
    if card.count() == 0:
        card = h4.locator("xpath=..")
    btn = card.locator('button:has-text("🚀 继续")').first
    if btn.count() == 0:
        return False
    btn.click()
    return True


def logout(page: Page) -> bool:
    try:
        # Sidebar may be collapsed; expand if needed.
        # Look for the 🔓 注销 button.
        btn = page.locator('button:has-text("🔓 注销")').first
        if btn.count() == 0:
            # Open sidebar
            toggle = page.locator('[data-testid="stSidebarCollapsedControl"]').first
            if toggle.count() > 0:
                toggle.click()
                time.sleep(0.5)
            btn = page.locator('button:has-text("🔓 注销")').first
        btn.wait_for(state="visible", timeout=5000)
        btn.click()
        time.sleep(1.0)
        wait_streamlit_idle(page)
        return True
    except Exception:
        return False


def run() -> int:
    report = Report()
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        context = browser.new_context(
            viewport={"width": 1440, "height": 900},
            ignore_https_errors=True,
            locale="zh-CN",
        )
        page = context.new_page()
        page.set_default_timeout(15000)

        # ---- XYC flow ----
        if not login(page, "XYC", "123456", report, "xyc"):
            report.add(StepResult("xyc-rest: skipped due to login fail", False, "", ""))
        else:
            # Step 3: project list >= 18 incl. expected names
            time.sleep(1.0)
            wait_streamlit_idle(page)
            s = shot(page, "xyc_03_project_list")
            names = list_projects(page)
            required = ["果蝠病毒动画", "黑洞", "薛定谔"]
            has_all = all(any(req in n for n in names) for req in required)
            ok = len(names) >= 18 and has_all
            report.add(StepResult(
                "xyc-3: project list >= 18 incl. 果蝠病毒动画/黑洞/薛定谔",
                ok,
                f"count={len(names)}; has_required={has_all}; sample={names[:5]}",
                s,
            ))
            (ARTIFACTS / "xyc_projects.json").write_text(
                json.dumps(names, ensure_ascii=False, indent=2), encoding="utf-8"
            )

            # Step 4: open 果蝠病毒动画, segments visible
            target = next((n for n in names if "果蝠病毒动画" in n), None)
            opened = False
            if target:
                opened = open_project_by_name(page, target)
            if opened:
                time.sleep(2.0)
                wait_streamlit_idle(page)
                # After clicking 继续, a stage-selection page appears. Pick first available stage.
                stage_btn = page.locator('button:has-text("继续当前阶段")').first
                if stage_btn.count() > 0:
                    try:
                        stage_btn.click()
                        time.sleep(2.0)
                        wait_streamlit_idle(page)
                    except Exception:
                        pass
                s = shot(page, "xyc_04_project_open")
                # segments timeline: look for table / segment list markers
                segs_visible = (
                    page.locator('text=片段').count() > 0
                    or page.locator('text=分段').count() > 0
                    or page.locator('text=时间').count() > 0
                )
                report.add(StepResult(
                    "xyc-4: open 果蝠病毒动画 → segments visible",
                    segs_visible,
                    f"segment-marker found={segs_visible}",
                    s,
                ))

                # Step 5: audio gracefully degrades (no crash). Heuristic:
                #   - page is still alive, no Streamlit unhandled exception banner.
                err_banner = (
                    page.locator('text=Uncaught').count()
                    + page.locator('text=Traceback').count()
                    + page.locator('text=RuntimeError').count()
                )
                s = shot(page, "xyc_05_audio_state")
                report.add(StepResult(
                    "xyc-5: audio missing handled gracefully (no crash banner)",
                    err_banner == 0,
                    f"error-banner-count={err_banner}",
                    s,
                ))
            else:
                report.add(StepResult(
                    "xyc-4: open 果蝠病毒动画",
                    False,
                    f"could not click 继续 for target={target!r}",
                    shot(page, "xyc_04_open_fail"),
                ))
                report.add(StepResult("xyc-5: audio degradation", False, "skipped (couldn't open project)", ""))

            # Step 6/7: logout and DYJ login -> SKIPPED (password unknown)
            logged_out = logout(page)
            s = shot(page, "xyc_06_after_logout")
            report.add(StepResult(
                "xyc-6: logout XYC", logged_out, "logout button clicked", s
            ))
            report.add(StepResult(
                "step-7: DYJ login + cross-user isolation",
                False,
                "SKIPPED: DYJ password unknown (hash ec31615b...). "
                "Reset & redeploy config to test.",
                "",
            ))

        browser.close()

    print(report.summary())
    out = ARTIFACTS / "report.json"
    out.write_text(
        json.dumps(
            [s.__dict__ for s in report.steps], ensure_ascii=False, indent=2
        ),
        encoding="utf-8",
    )
    print(f"\nJSON report: {out}")
    failures = [s for s in report.steps if not s.passed]
    return 0 if not failures else 1


if __name__ == "__main__":
    sys.exit(run())
