# -*- coding: utf-8 -*-
import re
import requests
from urllib.parse import urljoin
from abc import ABCMeta, abstractmethod
from typing import Dict, Optional, Any
from bs4 import BeautifulSoup

from app.log import logger
from app.utils.http import RequestUtils
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

    @abstractmethod
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
                    logger.debug(f"[{site_name}] 页面内容摘要: {content_preview}")
                    
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

    def _get_user_id(self, site_info: dict) -> Optional[str]:
        """
        获取用户ID
        :param site_info: 站点信息
        :return: 用户ID
        """
        try:
            import time
            start_time = time.time()
            
            site_url = site_info.get("url", "")
            if not site_url:
                logger.error("获取用户ID失败: 站点URL为空")
                return None
            
            # 只尝试最常用的几个页面，避免过多请求
            user_pages = [
                "usercp.php",  # 最常用的用户控制面板
                "userdetails.php",  # 用户详情页
                ""  # 首页
            ]
            
            user_id = None
            visited_urls = set()  # 避免重复请求
            max_attempts = 3  # 最多尝试3个页面
            total_timeout = 20  # 总超时时间缩短为20秒
            
            for page in user_pages:
                # 检查总超时
                if time.time() - start_time > total_timeout:
                    logger.debug(f"获取用户ID总超时 (>{total_timeout}秒)")
                    break
                    
                try:
                    logger.debug(f"尝试从 {page or '首页'} 获取用户ID")
                    
                    # 构建请求URL
                    session = self._init_session(site_info)
                    if page:
                        user_url = urljoin(site_url, page)
                    else:
                        user_url = site_url.rstrip("/")
                    
                    # 避免重复请求
                    if user_url in visited_urls:
                        logger.debug(f"已访问过 {user_url}，跳过")
                        continue
                    visited_urls.add(user_url)
                    
                    # 使用优化的超时设置，参考hdhivesign插件
                    response = session.get(user_url, timeout=(5, 30))  # 连接超时5秒，读取超时30秒
                    response.raise_for_status()
                    
                    logger.debug(f"成功访问 {user_url}")
                    html_content = response.text
                    
                    # 先尝试从HTML中快速提取用户ID（最常用的方法）
                    from bs4 import BeautifulSoup
                    soup = BeautifulSoup(html_content, 'html.parser')
                    
                    # 方法1: 从个人信息链接获取（最可靠的方法）
                    user_link = soup.select_one('a[href*="userdetails.php"]')
                    if user_link and 'href' in user_link.attrs:
                        user_id_match = re.search(r'id=(\d+)', user_link['href'])
                        if user_id_match:
                            user_id = user_id_match.group(1)
                            logger.debug(f"从个人信息链接获取到用户ID: {user_id}")
                            break
                    
                    # 方法2: 从邀请链接获取
                    invite_link = soup.select_one('a[href*="invite.php?id="]')
                    if invite_link and 'href' in invite_link.attrs:
                        user_id_match = re.search(r'id=(\d+)', invite_link.attrs['href'])
                        if user_id_match:
                            user_id = user_id_match.group(1)
                            logger.debug(f"从邀请链接获取到用户ID: {user_id}")
                            break
                    
                    # 方法3: 从当前页面URL获取
                    if any(p in page for p in ["userdetails.php", "usercp.php", "u.php"]):
                        user_id_match = re.search(r'id=(\d+)', response.url)
                        if user_id_match:
                            user_id = user_id_match.group(1)
                            logger.debug(f"从页面URL获取到用户ID: {user_id}")
                            break
                    
                    # 方法4: 从页面中的JavaScript变量获取
                    script_tags = soup.select('script')
                    for script in script_tags:
                        script_content = script.string or ''
                        if script_content:
                            # 匹配常见的用户ID变量
                            user_id_match = re.search(r'(?:userid|uid|id)\s*[:=]\s*(\d+)', script_content, re.IGNORECASE)
                            if user_id_match:
                                user_id = user_id_match.group(1)
                                logger.debug(f"从JavaScript变量获取到用户ID: {user_id}")
                                break
                    if user_id:
                        break
                    
                    # 快速检查是否是JSON响应
                    response_text = html_content.strip()
                    if response_text.startswith('{') or response_text.startswith('['):
                        logger.debug(f"页面返回JSON格式，尝试解析")
                        try:
                            import json
                            json_data = json.loads(response_text)
                            
                            # 简单查找常见的用户ID字段
                            def find_simple_user_id(data):
                                if isinstance(data, dict):
                                    # 只检查最常见的几个字段
                                    for key in ['userid', 'uid', 'id', 'user_id']:
                                        if key in data and isinstance(data[key], (int, str)):
                                            return str(data[key])
                                    # 检查嵌套结构
                                    for key in ['user', 'profile', 'current_user']:
                                        if key in data and isinstance(data[key], dict):
                                            result = find_simple_user_id(data[key])
                                            if result:
                                                return result
                                return None
                            
                            user_id = find_simple_user_id(json_data)
                            if user_id:
                                logger.debug(f"从JSON响应获取到用户ID: {user_id}")
                                break
                        except json.JSONDecodeError:
                            logger.debug("JSON解析失败，继续尝试其他方法")
                
                except requests.exceptions.Timeout:
                    logger.debug(f"从 {page or '首页'} 获取用户ID超时")
                    # 继续尝试下一个页面
                    continue
                except requests.exceptions.HTTPError as e:
                    logger.debug(f"从 {page or '首页'} 获取用户ID时HTTP错误: {str(e)}")
                    # 继续尝试下一个页面
                    continue
                except Exception as e:
                    logger.debug(f"从 {page or '首页'} 获取用户ID时出错: {str(e)}")
                    # 继续尝试下一个页面
                    continue
            
            # 如果所有方法都失败，尝试从当前会话的Cookie中获取
            if not user_id:
                logger.debug("尝试从Cookie中获取用户ID")
                session = self._init_session(site_info)
                cookies = session.cookies.get_dict()
                
                # 检查常见的Cookie名称
                for cookie_name in ['userid', 'uid', 'PHPSESSID']:
                    if cookie_name in cookies:
                        cookie_value = cookies[cookie_name]
                        # 尝试从Cookie值中提取数字ID
                        id_match = re.search(r'(\d+)', cookie_value)
                        if id_match:
                            user_id = id_match.group(1)
                            logger.debug(f"从Cookie {cookie_name} 获取到用户ID: {user_id}")
                            break
            
            logger.debug(f"获取用户ID完成，耗时: {time.time() - start_time:.2f}秒，结果: {user_id}")
            return user_id
        except Exception as e:
            logger.error(f"获取用户ID失败: {str(e)}")
            return None

    def parse_response(self, html_content: str, xpath_rules: Dict[str, str]) -> Dict[str, Optional[str]]:
        """
        解析HTML内容，提取邀请人信息
        :param html_content: HTML内容
        :param xpath_rules: XPath规则字典
        :return: 邀请人信息字典
        """
        from lxml import etree
        try:
            logger.debug(f"开始解析HTML内容，XPath规则数量: {len(xpath_rules)}")
            tree = etree.HTML(html_content)
            if not tree:
                logger.error("HTML解析树构建失败")
                return {}
            
            result = {}
            for key, xpath in xpath_rules.items():
                logger.debug(f"尝试使用XPath规则解析: {key} -> {xpath}")
                try:
                    elements = tree.xpath(xpath)
                    logger.debug(f"XPath解析结果数量: {len(elements)}")
                    if elements:
                        # 提取元素内所有文本
                        text_content = "".join(elements[0].xpath(".//text()")).strip()
                        logger.debug(f"解析到{key}的文本内容: {text_content}")
                        result[key] = text_content
                    else:
                        logger.debug(f"XPath {xpath} 未匹配到任何元素")
                        result[key] = None
                except Exception as e:
                    logger.error(f"使用XPath规则 {xpath} 解析 {key} 失败: {str(e)}")
                    result[key] = None
            
            logger.debug(f"解析完成，结果: {result}")
            return result
        except Exception as e:
            logger.error(f"解析邀请人信息失败: {str(e)}")
            logger.exception(e)
            return {}
