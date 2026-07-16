import threading
from typing import Optional

from app.log import logger
from app.utils.http import RequestUtils


class LocalOcrHelper:
    """Download captcha images and recognize them with the plugin-local OCR model."""

    _engine = None
    _engine_lock = threading.Lock()
    _classification_lock = threading.Lock()

    @classmethod
    def get_captcha_text(cls, image_url: str, cookie: Optional[str] = None,
                         ua: Optional[str] = None, proxies: Optional[dict] = None,
                         referer: Optional[str] = None,
                         timeout: Optional[int] = None,
                         uppercase: bool = False) -> str:
        if not image_url:
            return ""

        image_res = RequestUtils(cookies=cookie,
                                 ua=ua,
                                 proxies=proxies,
                                 referer=referer,
                                 timeout=timeout or 20).get_res(image_url)
        if image_res is None:
            logger.warn(f"验证码图片下载失败：{image_url}")
            return ""
        try:
            if image_res.status_code != 200:
                logger.warn(f"验证码图片下载失败，状态码：{image_res.status_code}")
                return ""
            content_type = (image_res.headers.get("content-type") or "").lower()
            if content_type and not content_type.startswith("image/"):
                logger.warn(f"验证码地址返回了非图片内容：{content_type}")
                return ""
            image_content = image_res.content
            if not image_content:
                logger.warn("验证码图片内容为空")
                return ""
        finally:
            image_res.close()

        engine = cls._get_engine()
        if engine is None:
            return ""

        try:
            with cls._classification_lock:
                result = engine.classification(image_content)
        except Exception as e:
            logger.error(f"本地OCR识别失败：{str(e)}")
            return ""
        result = "".join(str(result or "").split())
        return result.upper() if uppercase else result

    @classmethod
    def _get_engine(cls):
        if cls._engine is not None:
            return cls._engine
        with cls._engine_lock:
            if cls._engine is not None:
                return cls._engine
            try:
                from ddddocr import DdddOcr

                cls._engine = DdddOcr(show_ad=False)
            except Exception as e:
                logger.error(f"本地OCR初始化失败，请确认ddddocr依赖已安装：{str(e)}")
                return None
        return cls._engine
