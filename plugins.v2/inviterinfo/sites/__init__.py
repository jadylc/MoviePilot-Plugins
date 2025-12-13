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

    def get_page_source(self, url: str, site_info: dict, retry: int = 3) -> str:
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
            site_url = site_info.get("url", "")
            if not site_url:
                logger.error("获取用户ID失败: 站点URL为空")
                return None
                
            # 扩展用户页面列表，增加更多可能的用户信息页面和API路径
            user_pages = [
                # 传统NexusPHP页面
                "usercp.php", "userdetails.php", "my.php", "profile.php", "index.php", "",
                "homepage.php", "dashboard.php", "member.php", "u.php", "users.php",
                "account.php", "settings.php", "preferences.php", "profile.php?mode=view",
                "user.php", "userinfo.php", "my_profile.php", "member.php?action=profile",
                "user.php?id", "userinfo.php?id", "member.php?id", "memberlist.php?mode=viewprofile",
                "showuser.php", "viewprofile.php", "user/profile", "users/profile", "member/profile",
                "user/member", "users/member", "member/member", "user/info", "users/info",
                "member/info", "user/details", "users/details", "member/details", "account/profile",
                "account/settings", "profile/settings", "settings/profile", "my/account", "my/profile",
                "my/settings", "home", "user/home", "member/home", "userpanel.php", "user_control_panel.php",
                "control_panel.php", "cp.php", "ucp.php", "membercp.php", "membercontrol.php",
                # 扩展的用户页面
                "users.php?id", "members.php?id", "memberlist.php?id", "profile.php?id",
                "user.php?action=profile", "member.php?mode=viewprofile", "members.php?mode=viewprofile",
                "userinfo.php?mode=view", "account.php?action=profile", "settings.php?mode=profile",
                "my.php?action=profile", "homepage.php?mode=profile", "dashboard.php?mode=profile",
                "profile.php?action=view", "usercp.php?mode=profile", "membercp.php?mode=profile",
                "ucp.php?mode=profile", "user.php?page=profile", "member.php?page=profile",
                "users.php?page=profile", "members.php?page=profile", "profile.php?page=view",
                "user.php?do=profile", "member.php?do=profile", "users.php?do=profile",
                "members.php?do=profile", "profile.php?do=view", "usercp.php?do=profile",
                "membercp.php?do=profile", "ucp.php?do=profile", "user.php?tab=profile",
                "member.php?tab=profile", "users.php?tab=profile", "members.php?tab=profile",
                "profile.php?tab=view", "usercp.php?tab=profile", "membercp.php?tab=profile",
                "ucp.php?tab=profile", "profile", "account", "settings", "preferences",
                "user/profile/view", "users/profile/view", "member/profile/view", "profile/view",
                # 新增用户中心页面
                "user-center.php", "member-center.php", "personal-center.php",
                "user_center.php", "member_center.php", "personal_center.php",
                "user_center", "member_center", "personal_center",
                # 新增其他可能的页面
                "me.php", "mydashboard.php", "mypage.php", "myhome.php",
                "profile/view", "profile/details", "profile/info",
                "member/view", "member/details", "member/info",
                # 新增更多通用页面
                "dashboard", "panel", "control", "settings", "preferences",
                "profile/edit", "profile/account", "profile/privacy",
                "user/account", "user/preferences", "user/privacy",
                "member/account", "member/preferences", "member/privacy",
                "user/settings", "member/settings", "user/preferences",
                # 新增API路径 - 基础路径
                "api/user/profile", "api/v1/user/profile", "api/v2/user/profile",
                "api/user/info", "api/v1/user/info", "api/v2/user/info",
                "api/member/profile", "api/v1/member/profile", "api/v2/member/profile",
                "api/member/info", "api/v1/member/info", "api/v2/member/info",
                # 新增API路径 - 扩展路径
                "api/profile", "api/v1/profile", "api/v2/profile",
                "api/me", "api/v1/me", "api/v2/me",
                "api/account", "api/v1/account", "api/v2/account",
                "api/user", "api/v1/user", "api/v2/user",
                "api/member", "api/v1/member", "api/v2/member",
                "api/user/current", "api/v1/user/current", "api/v2/user/current",
                "api/member/current", "api/v1/member/current", "api/v2/member/current",
                "api/auth/profile", "api/v1/auth/profile", "api/v2/auth/profile",
                "api/auth/user", "api/v1/auth/user", "api/v2/auth/user",
                # 新增API路径 - JSON API
                "api/json/profile", "api/json/user", "api/json/me",
                "api/json/member", "api/json/userinfo",
                "api/json/v1/profile", "api/json/v1/user", "api/json/v1/me",
                # 新增API路径 - 其他格式
                "api/rest/user/profile", "api/rest/member/profile",
                "api/rest/user/info", "api/rest/member/info",
                "api/graphql", "graphql", "api/v1/graphql", "api/v2/graphql",
                # 新增现代PT站点路径
                "user", "member", "account", "profile", "settings",
                "user/profile", "member/profile", "account/profile",
                "user/settings", "member/settings", "account/settings",
                "user/info", "member/info", "account/info",
                "user/details", "member/details", "account/details",
                # 新增移动端适配路径
                "m/user/profile", "m/member/profile", "m/account/profile",
                "mobile/user/profile", "mobile/member/profile", "mobile/account/profile",
                "m/user/info", "m/member/info", "mobile/user/info", "mobile/member/info"
            ]
            user_id = None
            visited_urls = set()  # 避免重复请求提升性能
            
            for page in user_pages:
                if user_id:
                    break
                    
                try:
                    logger.debug(f"尝试从 {page} 获取用户ID")
                    # 尝试访问个人信息页面
                    session = self._init_session(site_info)
                    if page:
                        usercp_url = urljoin(site_url, page)
                    else:
                        usercp_url = site_url.rstrip("/")
                    
                    # 避免重复请求提升性能
                    if usercp_url in visited_urls:
                        logger.debug(f"已访问过 {usercp_url}，跳过")
                        continue
                    visited_urls.add(usercp_url)
                    
                    response = session.get(usercp_url, timeout=(5, site_info.get("timeout", 20)))
                    response.raise_for_status()
                    
                    logger.debug(f"成功访问 {usercp_url}，页面大小: {len(response.text)} 字节")
                    
                    # 解析页面获取用户ID
                    html_content = response.text
                    
                    # 新增方法0: 先检查是否是JSON响应
                    response_text = html_content.strip()
                    
                    # 检查是否是JSONP响应
                    is_jsonp = False
                    if response_text.startswith('(') and 'callback' in response_text.lower():
                        # 尝试提取JSONP中的JSON数据
                        try:
                            import re
                            json_match = re.search(r'\((.*)\)', response_text)
                            if json_match:
                                response_text = json_match.group(1).strip()
                                is_jsonp = True
                                logger.debug(f"检测到JSONP响应，已提取JSON数据")
                        except Exception as e:
                            logger.debug(f"JSONP响应解析失败: {str(e)}")
                    
                    # 检查是否是JSON响应
                    if response_text.startswith('{') or response_text.startswith('['):
                        logger.debug(f"页面返回{'JSONP' if is_jsonp else 'JSON'}格式，尝试直接解析")
                        try:
                            import json
                            json_data = json.loads(response_text)
                            
                            # 递归查找用户ID
                            def find_user_id(data):
                                if isinstance(data, dict):
                                    # 检查常见的用户ID字段
                                    for key, value in data.items():
                                        # 支持更多的用户ID字段名称
                                        id_keys = ['userid', 'uid', 'id', 'user_id', 'member_id', 'memberid',
                                                  'useridstr', 'uidstr', 'idstr', 'user_id_str', 'member_id_str',
                                                  'user', 'member', 'account', 'profile', 'current_user', 'me',
                                                  'user_iden', 'member_iden', 'identity', 'identification',
                                                  'username', 'user_name', 'membername', 'member_name', 'name',
                                                  'login', 'loginname', 'login_name', 'nickname', 'nick_name',
                                                  'handle', 'handle_name', 'screenname', 'screen_name']
                                        
                                        # 检查当前字段是否是用户ID
                                        if key.lower() in id_keys:
                                            if isinstance(value, (int, str)):
                                                # 支持数字和字符串类型的用户ID
                                                if str(value).strip() and not str(value).isdigit():
                                                    # 字符串类型用户ID，确保不是空值
                                                    logger.debug(f"发现字符串类型用户ID: {value}")
                                                    return str(value)
                                                elif str(value).isdigit():
                                                    # 数字类型用户ID
                                                    return str(value)
                                            elif isinstance(value, dict):
                                                # 如果是嵌套字典，继续查找
                                                result = find_user_id(value)
                                                if result:
                                                    return result
                                        
                                        # 检查是否有嵌套的用户信息结构
                                        if key.lower() in ['user', 'member', 'account', 'profile', 'current_user', 'me',
                                                         'login_user', 'authenticated_user', 'logged_in_user',
                                                         'user_info', 'member_info', 'user_profile', 'member_profile'] and isinstance(value, dict):
                                            result = find_user_id(value)
                                            if result:
                                                return result
                                        
                                        # 递归检查其他字段
                                        result = find_user_id(value)
                                        if result:
                                            return result
                                elif isinstance(data, list):
                                    for item in data:
                                        result = find_user_id(item)
                                        if result:
                                            return result
                                return None
                            
                            # 尝试直接从JSON数据中获取用户ID
                            user_id = find_user_id(json_data)
                            
                            # 如果没有找到，尝试检查GraphQL响应结构
                            if not user_id and isinstance(json_data, dict):
                                # 检查GraphQL data字段
                                if 'data' in json_data:
                                    user_id = find_user_id(json_data['data'])
                                # 检查GraphQL payload字段
                                elif 'payload' in json_data:
                                    user_id = find_user_id(json_data['payload'])
                                # 检查GraphQL response字段
                                elif 'response' in json_data:
                                    user_id = find_user_id(json_data['response'])
                            
                            if user_id:
                                logger.debug(f"从{'JSONP' if is_jsonp else 'JSON'}响应中获取到用户ID: {user_id}")
                                break
                        except json.JSONDecodeError as e:
                            logger.debug(f"{'JSONP' if is_jsonp else 'JSON'}解析失败: {str(e)}，继续使用HTML解析")
                        except Exception as e:
                            logger.debug(f"解析{'JSONP' if is_jsonp else 'JSON'}响应时发生错误: {str(e)}，继续使用HTML解析")
                    
                    # 解析HTML内容
                    soup = BeautifulSoup(html_content, 'html.parser')
                    
                    # 方法1: 从个人信息链接获取
                    user_link = soup.select_one('a[href*="userdetails.php"]')
                    if user_link and 'href' in user_link.attrs:
                        user_id_match = re.search(r'id=(\d+)', user_link['href'])
                        if user_id_match:
                            user_id = user_id_match.group(1)
                            logger.debug(f"从个人信息链接获取到用户ID: {user_id}")
                            break
                    
                    # 方法2: 从其他用户相关链接获取
                    profile_link = soup.select_one('a[href*="my.php"]') or soup.select_one('a[href*="profile.php"]')
                    if profile_link and 'href' in profile_link.attrs:
                        user_id_match = re.search(r'id=(\d+)', profile_link['href'])
                        if user_id_match:
                            user_id = user_id_match.group(1)
                            logger.debug(f"从个人资料链接获取到用户ID: {user_id}")
                            break
                    
                    # 方法3: 直接从当前页面URL获取
                    if any(p in page for p in ["userdetails.php", "my.php", "profile.php", "usercp.php", "u.php", 
                                               "member.php", "user.php", "userinfo.php"]):
                        user_id_match = re.search(r'id=(\d+)', response.url)
                        if user_id_match:
                            user_id = user_id_match.group(1)
                            logger.debug(f"从当前页面URL获取到用户ID: {user_id}")
                            break
                    
                    # 方法4: 从页面中的JavaScript变量获取（超级增强版）
                    # 支持更多的变量名和声明方式
                    js_patterns = [
                        # 标准NexusPHP用户ID变量
                        r'(?:var|const|let)\s+userid\s*[:=]\s*(\d+)(?:;|\s)',
                        r'(?:var|const|let)\s+USERID\s*[:=]\s*(\d+)(?:;|\s)',
                        r'(?:var|const|let)\s+UserId\s*[:=]\s*(\d+)(?:;|\s)',
                        r'(?:var|const|let)\s+userID\s*[:=]\s*(\d+)(?:;|\s)',
                        # 其他常见的用户ID变量名
                        r'(?:var|const|let)\s+uid\s*[:=]\s*(\d+)(?:;|\s)',
                        r'(?:var|const|let)\s+UID\s*[:=]\s*(\d+)(?:;|\s)',
                        r'(?:var|const|let)\s+memberid\s*[:=]\s*(\d+)(?:;|\s)',
                        r'(?:var|const|let)\s+MEMBERID\s*[:=]\s*(\d+)(?:;|\s)',
                        r'(?:var|const|let)\s+MemberID\s*[:=]\s*(\d+)(?:;|\s)',
                        r'(?:var|const|let)\s+memberID\s*[:=]\s*(\d+)(?:;|\s)',
                        r'(?:var|const|let)\s+myid\s*[:=]\s*(\d+)(?:;|\s)',
                        r'(?:var|const|let)\s+MYID\s*[:=]\s*(\d+)(?:;|\s)',
                        r'(?:var|const|let)\s+MyId\s*[:=]\s*(\d+)(?:;|\s)',
                        # 不指定声明类型的变量
                        r'userid\s*[:=]\s*(\d+)(?:;|\s)',
                        r'USERID\s*[:=]\s*(\d+)(?:;|\s)',
                        r'UserId\s*[:=]\s*(\d+)(?:;|\s)',
                        r'userID\s*[:=]\s*(\d+)(?:;|\s)',
                        r'uid\s*[:=]\s*(\d+)(?:;|\s)',
                        r'UID\s*[:=]\s*(\d+)(?:;|\s)',
                        r'memberid\s*[:=]\s*(\d+)(?:;|\s)',
                        r'MEMBERID\s*[:=]\s*(\d+)(?:;|\s)'
                    ]
                    for pattern in js_patterns:
                        user_id_match = re.search(pattern, html_content)
                        if user_id_match:
                            user_id = user_id_match.group(1)
                            logger.debug(f"从JavaScript变量获取到用户ID: {user_id}")
                            break
                    if user_id:
                        break
                    
                    # 方法5: 从页面中的JavaScript变量获取（更宽松的匹配）
                    js_user_id_matches = re.findall(r'userid\s*[:=]\s*(\d+)', html_content, re.IGNORECASE)
                    if not js_user_id_matches:
                        # 尝试其他常见的用户ID变量名
                        js_user_id_matches = re.findall(r'uid\s*[:=]\s*(\d+)', html_content, re.IGNORECASE) + \
                                            re.findall(r'memberid\s*[:=]\s*(\d+)', html_content, re.IGNORECASE) + \
                                            re.findall(r'myid\s*[:=]\s*(\d+)', html_content, re.IGNORECASE)
                    if js_user_id_matches:
                        user_id = js_user_id_matches[0]
                        logger.debug(f"从JavaScript中获取到用户ID: {user_id}")
                        break
                    
                    # 方法6: 从用户中心链接获取
                    usercp_links = soup.select('a[href*="usercp.php"]')
                    for link in usercp_links:
                        if 'href' in link.attrs:
                            user_id_match = re.search(r'id=(\d+)', link['href'])
                            if user_id_match:
                                user_id = user_id_match.group(1)
                                logger.debug(f"从用户中心链接获取到用户ID: {user_id}")
                                break
                    if user_id:
                        break
                    
                    # 方法7: 从Cookie中获取（增强版）
                    cookies = session.cookies.get_dict()
                    for cookie_name, cookie_value in cookies.items():
                        cookie_name_lower = cookie_name.lower()
                        if cookie_value.isdigit():
                            # 优先匹配明确的用户ID相关Cookie
                            if any(keyword in cookie_name_lower for keyword in ['userid', 'user_id', 'id_user', 
                                                                                'memberid', 'member_id', 'id_member', 
                                                                                'uid', 'id', 'myid', 'user_id', 'user_id_',
                                                                                'user_id_cookie', 'login_user_id', 'current_user_id']):
                                user_id = cookie_value
                                logger.debug(f"从Cookie {cookie_name} 获取到用户ID: {user_id}")
                                break
                            elif any(keyword in cookie_name_lower for keyword in ['user', 'member']):
                                # 检查是否是纯数字的用户ID
                                if 1 < len(cookie_value) < 10:
                                    user_id = cookie_value
                                    logger.debug(f"从Cookie {cookie_name} 获取到用户ID: {user_id}")
                                    break
                    if user_id:
                        break
                    
                    # 方法8: 从所有链接中获取（增强版）
                    all_links = soup.select('a[href]')
                    for link in all_links:
                        href = link['href']
                        if 'id=' in href:
                            user_id_match = re.search(r'id=(\d+)', href)
                            if user_id_match:
                                user_id = user_id_match.group(1)
                                logger.debug(f"从链接 {href} 获取到用户ID: {user_id}")
                                break
                        if 'user' in href.lower() and '=' in href:
                            user_id_match = re.search(r'user=?(\d+)', href.lower())
                            if user_id_match:
                                user_id = user_id_match.group(1)
                                logger.debug(f"从用户链接 {href} 获取到用户ID: {user_id}")
                                break
                        if 'uid=' in href.lower():
                            user_id_match = re.search(r'uid=(\d+)', href.lower())
                            if user_id_match:
                                user_id = user_id_match.group(1)
                                logger.debug(f"从UID链接 {href} 获取到用户ID: {user_id}")
                                break
                        if 'memberid=' in href.lower():
                            user_id_match = re.search(r'memberid=(\d+)', href.lower())
                            if user_id_match:
                                user_id = user_id_match.group(1)
                                logger.debug(f"从MemberID链接 {href} 获取到用户ID: {user_id}")
                                break
                    if user_id:
                        break
                    
                    # 方法9: 从表单隐藏字段获取（增强版）
                    hidden_fields = soup.select('input[type="hidden"]')
                    for field in hidden_fields:
                        name = field.get('name', '')
                        id_attr = field.get('id', '')
                        value = field.get('value', '')
                        if value and value.isdigit():
                            if any(keyword in name.lower() or keyword in id_attr.lower() for keyword in 
                                   ['userid', 'user_id', 'id_user', 'memberid', 'member_id', 'id_member', 
                                    'user', 'member', 'uid', 'id', 'myid', 'login_user', 'current_user']):
                                user_id = value
                                logger.debug(f"从隐藏字段 {name or id_attr} 获取到用户ID: {user_id}")
                                break
                    if user_id:
                        break
                    
                    # 方法10: 从页面标题获取（增强版）
                    title = soup.title.string if soup.title else ""
                    user_id_match = re.search(r'用户(\d+)', title) or re.search(r'User\s*(\d+)', title) or \
                                   re.search(r'会员(\d+)', title) or re.search(r'Member\s*(\d+)', title) or \
                                   re.search(r'ID(\d+)', title) or re.search(r'ID\s*(\d+)', title) or \
                                   re.search(r'用户ID(\d+)', title) or re.search(r'User\s*ID(\d+)', title)
                    if user_id_match:
                        user_id = user_id_match.group(1)
                        logger.debug(f"从页面标题获取到用户ID: {user_id}")
                        break
                    
                    # 方法11: 从页面中的任意位置提取数字ID（作为最后手段，增强版）
                    all_ids = re.findall(r'userid\s*[:=]\s*(\d+)', html_content, re.IGNORECASE) + \
                             re.findall(r'user\s*[:=]\s*(\d+)', html_content, re.IGNORECASE) + \
                             re.findall(r'id\s*[:=]\s*(\d+)', html_content, re.IGNORECASE) + \
                             re.findall(r'memberid\s*[:=]\s*(\d+)', html_content, re.IGNORECASE) + \
                             re.findall(r'member\s*[:=]\s*(\d+)', html_content, re.IGNORECASE) + \
                             re.findall(r'userid=(\d+)', html_content, re.IGNORECASE) + \
                             re.findall(r'user=(\d+)', html_content, re.IGNORECASE) + \
                             re.findall(r'id=(\d+)', html_content, re.IGNORECASE) + \
                             re.findall(r'memberid=(\d+)', html_content, re.IGNORECASE) + \
                             re.findall(r'member=(\d+)', html_content, re.IGNORECASE) + \
                             re.findall(r'uid=(\d+)', html_content, re.IGNORECASE) + \
                             re.findall(r'user_id=(\d+)', html_content, re.IGNORECASE) + \
                             re.findall(r'member_id=(\d+)', html_content, re.IGNORECASE) + \
                             re.findall(r'loginid=(\d+)', html_content, re.IGNORECASE) + \
                             re.findall(r'userloginid=(\d+)', html_content, re.IGNORECASE) + \
                             re.findall(r'login_user_id=(\d+)', html_content, re.IGNORECASE) + \
                             re.findall(r'current_user_id=(\d+)', html_content, re.IGNORECASE)
                    
                    # 统计所有找到的ID，选择出现次数最多的
                    id_counts = {}
                    for id_candidate in all_ids:
                        if id_candidate.isdigit() and 1 < len(id_candidate) < 12:  # 扩展ID长度范围
                            id_counts[id_candidate] = id_counts.get(id_candidate, 0) + 1
                    
                    # 选择出现次数最多的ID
                    if id_counts:
                        user_id = max(id_counts, key=id_counts.get)
                        logger.debug(f"从页面文本中提取到用户ID: {user_id} (出现 {id_counts[user_id]} 次)")
                        break
                    
                    # 方法12: 从meta标签获取
                    meta_tags = soup.select('meta')
                    for meta in meta_tags:
                        content = meta.get('content', '')
                        name = meta.get('name', '')
                        if 'user' in name.lower() and 'id' in name.lower() and content.isdigit():
                            user_id = content
                            logger.debug(f"从meta标签 {name} 获取到用户ID: {user_id}")
                            break
                    if user_id:
                        break
                    
                    # 方法13: 从script标签内容中获取（专门针对JSON-LD和其他结构化数据）
                    script_tags = soup.select('script')
                    for script in script_tags:
                        script_content = script.string or ''
                        if script_content:
                            # 尝试匹配JSON-LD中的用户ID
                            user_id_match = re.search(r'"userid"\s*:\s*(\d+)', script_content, re.IGNORECASE)
                            if not user_id_match:
                                user_id_match = re.search(r'"id"\s*:\s*(\d+)', script_content, re.IGNORECASE)
                            if not user_id_match:
                                user_id_match = re.search(r'"uid"\s*:\s*(\d+)', script_content, re.IGNORECASE)
                            if user_id_match:
                                user_id = user_id_match.group(1)
                                logger.debug(f"从script标签获取到用户ID: {user_id}")
                                break
                    if user_id:
                        break
                    
                    # 方法14: 从页面中的特定元素获取（如用户面板、头像区域等）
                    user_panel_elements = soup.select('.userpanel, .user-info, .profile-info, .user-header, .avatar-container')
                    for elem in user_panel_elements:
                        elem_html = str(elem)
                        user_id_match = re.search(r'id=(\d+)', elem_html)
                        if user_id_match:
                            user_id = user_id_match.group(1)
                            logger.debug(f"从用户面板元素获取到用户ID: {user_id}")
                            break
                    if user_id:
                        break
                              
                except requests.exceptions.Timeout:
                    logger.debug(f"从 {page} 获取用户ID超时")
                    continue
                except requests.exceptions.ConnectionError:
                    logger.debug(f"从 {page} 获取用户ID连接失败")
                    continue
                except requests.exceptions.HTTPError as e:
                    if e.response.status_code in [404, 403, 500, 503]:
                        logger.debug(f"从 {page} 获取用户ID遇到HTTP错误 {e.response.status_code}")
                        continue
                    else:
                        logger.debug(f"从 {page} 获取用户ID失败: {str(e)}")
                        continue
                except Exception as e:
                    logger.debug(f"从 {page} 获取用户ID失败: {str(e)}")
                    continue
            
            # 特殊处理: 尝试直接从首页获取用户ID（增强版）
            if not user_id:
                logger.debug("尝试特殊方法获取用户ID")
                try:
                    session = self._init_session(site_info)
                    index_url = site_url.rstrip("/")
                    response = session.get(index_url, timeout=(5, site_info.get("timeout", 20)))
                    response.raise_for_status()
                    html_content = response.text
                    
                    # 尝试从JavaScript中获取userid变量（支持更多变量名）
                    js_patterns = [
                        r'var\s+userid\s*=\s*(\d+);',
                        r'var\s+uid\s*=\s*(\d+);',
                        r'var\s+memberid\s*=\s*(\d+);',
                        r'const\s+userid\s*=\s*(\d+);',
                        r'const\s+uid\s*=\s*(\d+);',
                        r'const\s+memberid\s*=\s*(\d+);',
                        r'let\s+userid\s*=\s*(\d+);',
                        r'let\s+uid\s*=\s*(\d+);',
                        r'let\s+memberid\s*=\s*(\d+);'
                    ]
                    
                    for pattern in js_patterns:
                        userid_matches = re.findall(pattern, html_content)
                        if userid_matches:
                            user_id = userid_matches[0]
                            logger.debug(f"从首页JavaScript中获取到用户ID: {user_id}")
                            break
                    
                    # 如果还是没找到，尝试从首页的链接中获取
                    if not user_id:
                        soup = BeautifulSoup(html_content, 'html.parser')
                        # 查找指向用户详情页的链接
                        user_links = soup.select('a[href*="userdetails.php"], a[href*="profile.php"], a[href*="user.php"]')
                        for link in user_links[:10]:  # 只检查前10个链接
                            href = link.get('href', '')
                            user_id_match = re.search(r'id=(\d+)', href)
                            if user_id_match:
                                user_id = user_id_match.group(1)
                                logger.debug(f"从首页用户链接获取到用户ID: {user_id}")
                                break
                except Exception as e:
                    logger.debug(f"特殊方法获取用户ID失败: {str(e)}")
            
            if user_id:
                logger.info(f"成功获取用户ID: {user_id}")
                return user_id
            else:
                logger.info("所有方法尝试后仍未找到用户ID")
                return None
        except Exception as e:
            logger.error(f"获取用户ID失败: {str(e)}")
            logger.exception(e)
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
