import importlib.util
import sys
import types
import unittest
from pathlib import Path
from unittest.mock import patch


ROOT = Path(__file__).resolve().parents[1]
OCR_PATH = ROOT / "plugins.v2" / "sitesign" / "ocr.py"


def _module(name, **attributes):
    module = types.ModuleType(name)
    for key, value in attributes.items():
        setattr(module, key, value)
    return module


class _Logger:
    def __getattr__(self, _name):
        return lambda *_args, **_kwargs: None


class _Response:
    status_code = 200
    content = b"captcha-image"
    headers = {"content-type": "image/png"}

    def __init__(self):
        self.closed = False

    def close(self):
        self.closed = True


class _RequestUtils:
    init_kwargs = None
    image_url = None
    response = None

    def __init__(self, **kwargs):
        type(self).init_kwargs = kwargs

    def get_res(self, image_url):
        type(self).image_url = image_url
        type(self).response = _Response()
        return type(self).response


class _Engine:
    image = None

    def classification(self, image):
        self.image = image
        return " 56 39m9\n"


def _load_ocr_module():
    stubs = {
        "app": _module("app"),
        "app.log": _module("app.log", logger=_Logger()),
        "app.utils": _module("app.utils"),
        "app.utils.http": _module("app.utils.http", RequestUtils=_RequestUtils),
    }
    spec = importlib.util.spec_from_file_location("local_ocr_under_test", OCR_PATH)
    module = importlib.util.module_from_spec(spec)
    with patch.dict(sys.modules, stubs):
        spec.loader.exec_module(module)
    return module


class LocalOcrTests(unittest.TestCase):
    def setUp(self):
        _RequestUtils.init_kwargs = None
        _RequestUtils.image_url = None
        _RequestUtils.response = None

    def test_downloads_with_site_request_context_and_recognizes_locally(self):
        module = _load_ocr_module()
        engine = _Engine()
        module.LocalOcrHelper._engine = engine

        result = module.LocalOcrHelper.get_captcha_text(
            image_url="https://tracker.example/image.php",
            cookie="session=abc",
            ua="test-agent",
            proxies={"https": "http://proxy.example"},
            referer="https://tracker.example/signin.php",
            timeout=12,
            uppercase=True,
        )

        self.assertEqual("5639M9", result)
        self.assertEqual(b"captcha-image", engine.image)
        self.assertTrue(_RequestUtils.response.closed)
        self.assertEqual("https://tracker.example/image.php", _RequestUtils.image_url)
        self.assertEqual("session=abc", _RequestUtils.init_kwargs["cookies"])
        self.assertEqual("test-agent", _RequestUtils.init_kwargs["ua"])
        self.assertEqual({"https": "http://proxy.example"}, _RequestUtils.init_kwargs["proxies"])
        self.assertEqual("https://tracker.example/signin.php", _RequestUtils.init_kwargs["referer"])
        self.assertEqual(12, _RequestUtils.init_kwargs["timeout"])

    def test_does_not_initialize_ocr_when_image_download_fails(self):
        module = _load_ocr_module()
        module.LocalOcrHelper._engine = None

        with patch.object(_RequestUtils, "get_res", return_value=None), \
                patch.object(module.LocalOcrHelper, "_get_engine") as get_engine:
            result = module.LocalOcrHelper.get_captcha_text(
                image_url="https://tracker.example/image.php"
            )

        self.assertEqual("", result)
        get_engine.assert_not_called()


if __name__ == "__main__":
    unittest.main()
