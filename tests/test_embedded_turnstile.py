import importlib.util
import sys
import types
import unittest
from pathlib import Path
from unittest.mock import patch


ROOT = Path(__file__).resolve().parents[1]
HANDLER_PATH = ROOT / "plugins.v2" / "sitesign" / "sites" / "__init__.py"


def _module(name, **attributes):
    module = types.ModuleType(name)
    for key, value in attributes.items():
        setattr(module, key, value)
    return module


class _Logger:
    def __getattr__(self, _name):
        return lambda *_args, **_kwargs: None


class _StringUtils:
    @staticmethod
    def url_equal(left, right):
        return right in left


class _RequestUtils:
    pass


class _PlaywrightHelper:
    pass


def _load_handler_module():
    settings = types.SimpleNamespace(PROXY=None, PROXY_SERVER=None)
    stubs = {
        "chardet": _module("chardet", detect=lambda _data: {"encoding": "utf-8"}),
        "ruamel": _module("ruamel"),
        "ruamel.yaml": _module("ruamel.yaml", CommentedMap=dict),
        "app": _module("app"),
        "app.core": _module("app.core"),
        "app.core.config": _module("app.core.config", settings=settings),
        "app.helper": _module("app.helper"),
        "app.helper.browser": _module("app.helper.browser", PlaywrightHelper=_PlaywrightHelper),
        "app.log": _module("app.log", logger=_Logger()),
        "app.utils": _module("app.utils"),
        "app.utils.http": _module("app.utils.http", RequestUtils=_RequestUtils),
        "app.utils.string": _module("app.utils.string", StringUtils=_StringUtils),
    }
    spec = importlib.util.spec_from_file_location("site_handler_under_test", HANDLER_PATH)
    module = importlib.util.module_from_spec(spec)
    with patch.dict(sys.modules, stubs):
        spec.loader.exec_module(module)
    return module


HANDLER_MODULE = _load_handler_module()
SiteHandler = HANDLER_MODULE._ISiteSigninHandler


class _Locator:
    first = None

    def __init__(self):
        self.first = self
        self.clicked = False

    @staticmethod
    def is_visible():
        return True

    def click(self, timeout=None):
        self.clicked = True


class _Frame:
    url = "https://challenges.cloudflare.com/cdn-cgi/challenge-platform/turnstile/if/ov2"

    def __init__(self):
        self.checkbox = _Locator()

    def locator(self, selector):
        if selector == 'input[type="checkbox"]':
            return self.checkbox
        raise LookupError(selector)


class _Page:
    pending_html = """
        <html><body>
          <p>连续签到 10 天后可获得奖励</p>
          <form id="attendance">
            <div class="cf-turnstile"></div>
            <input name="cf-turnstile-response" value="valid-token">
          </form>
        </body></html>
    """
    success_html = "<html><body>本次签到获得 100 个魔力值</body></html>"

    def __init__(self):
        self.submitted = False
        self.frame = _Frame()
        self.frames = [self.frame]

    def content(self):
        return self.success_html if self.submitted else self.pending_html

    def evaluate(self, _script):
        self.submitted = True
        return True

    @staticmethod
    def wait_for_timeout(_milliseconds):
        return None


class _TokenReadyPage(_Page):
    token_html = """
        <html><body>
          <form name="attendance">
            <input name="cf-turnstile-response" value="valid-token">
          </form>
        </body></html>
    """

    def content(self):
        return self.success_html if self.submitted else self.token_html

    def evaluate(self, script):
        if 'form[name="attendance"]' not in script:
            return False
        self.submitted = True
        return True


class _CoordinateElement:
    @staticmethod
    def bounding_box():
        return {"x": 100, "y": 200, "width": 300, "height": 65}


class _Mouse:
    def __init__(self):
        self.click_position = None

    def click(self, x, y):
        self.click_position = (x, y)


class _CoordinatePage:
    frames = []

    def __init__(self):
        self.mouse = _Mouse()

    @staticmethod
    def query_selector_all(selector):
        if selector == 'iframe[src*="challenges.cloudflare.com"]':
            return [_CoordinateElement()]
        return []


class _BrowserPage(_Page):
    def __init__(self):
        super().__init__()
        self.default_timeout = None
        self.goto_args = None
        self.closed = False

    def set_default_timeout(self, timeout):
        self.default_timeout = timeout

    def goto(self, url, wait_until=None, timeout=None):
        self.goto_args = (url, wait_until, timeout)

    def close(self):
        self.closed = True


class _BrowserContext:
    def __init__(self):
        self.page = _BrowserPage()
        self.cookies = None
        self.closed = False

    def add_cookies(self, cookies):
        self.cookies = cookies

    def new_page(self):
        return self.page

    def close(self):
        self.closed = True


class _LoginPage:
    frames = []

    @staticmethod
    def content():
        return """
            <form action="takelogin.php">
              <input name="username"><input name="password">
            </form>
        """

    @staticmethod
    def wait_for_timeout(_milliseconds):
        return None


class EmbeddedTurnstileTests(unittest.TestCase):
    def test_detects_attendance_form_with_embedded_turnstile(self):
        self.assertTrue(SiteHandler.has_embedded_turnstile(_Page.pending_html))
        self.assertTrue(SiteHandler.has_embedded_turnstile(
            "<form name='attendance'><div class='cf-turnstile'></div></form>"
        ))
        self.assertTrue(SiteHandler.has_embedded_turnstile(
            "<form id='attendance'>请耐心等待签到验证程序加载</form>"
        ))
        self.assertFalse(SiteHandler.has_embedded_turnstile("<div class='cf-turnstile'></div>"))
        self.assertFalse(SiteHandler.has_embedded_turnstile(
            "<form id='profile'></form><a href='attendance.php'></a><div class='cf-turnstile'></div>"
        ))

    def test_instruction_text_does_not_count_as_success(self):
        self.assertFalse(SiteHandler.sign_in_result(
            "连续签到 10 天后可获得额外奖励",
            SiteHandler._turnstile_succeed_regex,
        ))
        self.assertTrue(SiteHandler.sign_in_result(
            "已连续签到 3 天，本次签到获得 100 魔力值",
            SiteHandler._turnstile_succeed_regex,
        ))

    def test_cookie_parser_falls_back_without_losing_malformed_names(self):
        cookies = SiteHandler._build_browser_cookies(
            "https://tracker.example/attendance.php",
            "session=abc; bad@name=value",
        )

        self.assertEqual(
            [
                {"name": "session", "value": "abc", "url": "https://tracker.example/"},
                {"name": "bad@name", "value": "value", "url": "https://tracker.example/"},
            ],
            cookies,
        )

    def test_browser_flow_clicks_widget_and_submits_original_form(self):
        page = _Page()

        state, message = SiteHandler._drive_turnstile_page(
            page, site="embedded-turnstile-site", timeout=1
        )

        self.assertTrue(state)
        self.assertEqual("签到成功", message)
        self.assertTrue(page.frame.checkbox.clicked)
        self.assertTrue(page.submitted)

    def test_browser_flow_submits_token_after_widget_disappears(self):
        page = _TokenReadyPage()

        with patch.object(SiteHandler, "has_embedded_turnstile", return_value=False):
            state, message = SiteHandler._drive_turnstile_page(
                page, site="embedded-turnstile-site", timeout=1
            )

        self.assertTrue(state)
        self.assertEqual("签到成功", message)
        self.assertTrue(page.submitted)

    def test_turnstile_click_falls_back_to_iframe_coordinates(self):
        page = _CoordinatePage()

        self.assertTrue(SiteHandler._click_turnstile(page))
        self.assertEqual((130, 232.5), page.mouse.click_position)

    def test_signin_uses_browser_cookie_store_without_waiting_for_networkidle(self):
        context = _BrowserContext()

        launch_kwargs = {}

        def launch_context(**kwargs):
            launch_kwargs.update(kwargs)
            return context

        cloakbrowser = _module(
            "cloakbrowser",
            launch_context=launch_context,
        )

        with patch.dict(sys.modules, {"cloakbrowser": cloakbrowser}):
            state, message = SiteHandler.signin_embedded_turnstile(
                site="embedded-turnstile-site",
                url="https://tracker.example/attendance.php",
                cookie="session=abc; passkey=value=with=equals",
                ua="test-agent",
                proxies={"server": "http://proxy.example"},
                timeout=10,
            )

        self.assertTrue(state)
        self.assertEqual("签到成功", message)
        self.assertEqual(
            [
                {
                    "name": "session",
                    "value": "abc",
                    "url": "https://tracker.example/",
                },
                {
                    "name": "passkey",
                    "value": "value=with=equals",
                    "url": "https://tracker.example/",
                },
            ],
            context.cookies,
        )
        self.assertEqual(
            ("https://tracker.example/attendance.php", "domcontentloaded", 60000),
            context.page.goto_args,
        )
        self.assertEqual(
            {
                "headless": False,
                "proxy": {"server": "http://proxy.example"},
                "user_agent": "test-agent",
                "humanize": True,
                "human_preset": "default",
            },
            launch_kwargs,
        )
        self.assertTrue(context.page.closed)
        self.assertTrue(context.closed)

    def test_browser_flow_fails_immediately_on_login_page(self):
        state, message = SiteHandler._drive_turnstile_page(
            _LoginPage(), site="embedded-turnstile-site", timeout=1
        )

        self.assertFalse(state)
        self.assertIn("Cookie已失效", message)


if __name__ == "__main__":
    unittest.main()
