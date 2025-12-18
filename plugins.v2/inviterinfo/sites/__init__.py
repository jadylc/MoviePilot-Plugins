# -*- coding: utf-8 -*-

import requests

from abc import ABCMeta, abstractmethod
from typing import Dict, Optional, Any
from bs4 import BeautifulSoup

from app.log import logger

from app.utils.string import StringUtils
from app.core.config import settings


class _IInviterInfoHandler(metaclass=ABCMeta):
    """
    实现站点邀请人信息获取的基类，所有站点邀请人信息获取类都需要继承此类，并实现match和get_inviter_info方法
    实现类放置到inviterinfo/sites目录下将会自动加载
    """
    # 匹配的站点Url，每一个实现类都需要设置为自己的站点Url
    site_url = ""
    # 站点名称
    site_name = ""

    def __init__(self):
        self._session = None  # 延迟初始化会话
        self._initialized = False  # 标记会话是否已初始化

    @classmethod
    def match(self, url: str) -> bool:
        """
        根据站点Url判断是否匹配当前站点邀请人信息获取类，大部分情况使用默认实现即可
        :param url: 站点Url
        :return: 是否匹配，如匹配则会调用该类的get_inviter_info方法
        """
        if StringUtils.url_equal(url, self.site_url):
            return True
        return False

    @abstractmethod
    def get_inviter_info(self, site_info: dict) -> Dict[str, Optional[str]]:
        """
        获取邀请人信息
        :param site_info: 站点信息，含有站点Url、站点Cookie、UA等信息
        :return: 邀请人信息字典，包含inviter_name、inviter_id、inviter_email等字段
        """
        pass

    def _init_session(self, site_info: dict) -> requests.Session:
        """
        初始化请求会话，复用已有会话
        :param site_info: 站点信息
        :return: 初始化后的会话
        """
        # 如果会话已存在且已初始化，则直接返回
        if self._session and self._initialized:
            logger.debug("复用已存在的会话")
            return self._session
        
        # 创建或重置会话
        if not self._session:
            logger.debug("创建新会话")
            self._session = requests.Session()
        else:
            logger.debug("重置现有会话")
            self._session.cookies.clear()
            self._session.headers.clear()
        
        # 设置请求头
        headers = {
            "User-Agent": site_info.get("ua", "Mozilla/5.0"),
            "Cookie": site_info.get("cookie", ""),
            "Referer": site_info.get("url", ""),
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
            "Accept-Language": "zh-CN,zh;q=0.8,en-US;q=0.5,en;q=0.3"
        }
        self._session.headers.update(headers)
        
        # 设置代理
        if site_info.get("proxy"):
            self._session.proxies = settings.PROXY
        else:
            self._session.proxies.clear()
        
        # 标记会话已初始化
        self._initialized = True
        logger.debug("会话初始化完成")
        return self._session

    def get_page_source(self, url: str, site_info: dict, retry: int = 2) -> str:
        """
        获取页面源码，支持重试
        :param url: Url地址
        :param site_info: 站点信息
        :param retry: 重试次数
        :return: 页面源码
        """
        site_name = site_info.get("name", "未知站点")
        logger.info(f"[{site_name}] 开始获取页面: {url}")
        
        try:
            session = self._init_session(site_info)
            timeout = site_info.get("timeout", 20)
            
            logger.debug(f"[{site_name}] 请求参数: timeout={timeout}, retry={retry}")
            logger.debug(f"[{site_name}] 请求头: {dict(session.headers)}")
            
            for i in range(retry):
                try:
                    logger.info(f"[{site_name}] 发送请求 (尝试 {i+1}/{retry}): GET {url}")
                    response = session.get(url, timeout=(5, timeout))
                    logger.debug(f"[{site_name}] 响应状态码: {response.status_code}")
                    logger.debug(f"[{site_name}] 响应头: {dict(response.headers)}")
                    
                    # 对4xx状态码不重试，直接返回
                    if 400 <= response.status_code < 500:
                        logger.error(f"[{site_name}] 客户端错误 (状态码: {response.status_code})，不再重试")
                        return ""
                        
                    response.raise_for_status()
                    logger.info(f"[{site_name}] 成功获取页面: {url} (尝试 {i+1}/{retry})")
                    logger.info(f"[{site_name}] 页面大小: {len(response.text)} 字节")
                    
                    # 返回前记录页面内容摘要（前100个字符）
                    content_preview = response.text[:100] + "..." if len(response.text) > 100 else response.text
                    logger.debug(f"[{site_name}] 页面内容: {response.text}")
                    
                    return response.text
                except requests.exceptions.ConnectionError as e:
                    logger.error(f"[{site_name}] 网络连接错误 (尝试 {i+1}/{retry}): {type(e).__name__}: {str(e)}")
                    logger.debug(f"[{site_name}] 错误详情: {e}")
                except requests.exceptions.Timeout as e:
                    logger.error(f"[{site_name}] 请求超时 (尝试 {i+1}/{retry}): {type(e).__name__}: {str(e)}")
                    logger.debug(f"[{site_name}] 错误详情: {e}")
                except requests.exceptions.HTTPError as e:
                    # 检查状态码，如果是4xx，不重试
                    if hasattr(e.response, 'status_code') and 400 <= e.response.status_code < 500:
                        logger.error(f"[{site_name}] HTTP错误 (状态码: {e.response.status_code})，不再重试")
                        return ""
                    logger.error(f"[{site_name}] HTTP错误 (尝试 {i+1}/{retry}): {type(e).__name__}: {str(e)}")
                    logger.debug(f"[{site_name}] 错误详情: {e}")
                except requests.exceptions.RequestException as e:
                    logger.error(f"[{site_name}] 请求错误 (尝试 {i+1}/{retry}): {type(e).__name__}: {str(e)}")
                    logger.debug(f"[{site_name}] 错误详情: {e}")
                
                if i < retry - 1:
                    import time
                    logger.debug(f"[{site_name}] 等待2秒后重试...")
                    time.sleep(2)
                else:
                    logger.error(f"[{site_name}] 获取页面最终失败: {url}，已重试 {retry} 次")
            
            logger.debug(f"[{site_name}] 返回空页面内容")
            return ""
        except Exception as e:
            logger.error(f"[{site_name}] 获取页面时发生未预期的错误: {type(e).__name__}: {str(e)}")
            logger.exception(e)
            return ""

