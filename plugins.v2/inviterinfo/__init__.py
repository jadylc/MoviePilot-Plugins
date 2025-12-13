from typing import Optional, Any, List, Dict, Tuple
from datetime import datetime
from threading import Lock

from app import schemas
from app.core.config import settings
from app.core.event import eventmanager, Event
from app.db.models.siteuserdata import SiteUserData
from app.db.site_oper import SiteOper
from app.helper.sites import SitesHelper
from app.log import logger
from app.plugins import _PluginBase
from app.schemas.types import EventType, NotificationType
from app.utils.string import StringUtils
from app.utils.http import RequestUtils
from app.utils.site import SiteUtils
from lxml import etree
from ruamel.yaml import CommentedMap

lock = Lock()


class InviterInfo(_PluginBase):
    # 插件名称
    plugin_name = "PT站邀请人统计"
    # 插件描述
    plugin_desc = "统计所有PT站的上家信息，包括邀请人信息和邮箱（如果隐私设置允许）。"
    # 插件图标
    plugin_icon = "user.png"
    # 插件版本
    plugin_version = "1.0"
    # 插件作者
    plugin_author = "MoviePilot"
    # 作者主页
    author_url = ""
    # 插件配置项ID前缀
    plugin_config_prefix = "inviterinfo_"
    # 加载顺序
    plugin_order = 1
    # 可使用的用户级别
    auth_level = 2

    # 配置属性
    _enabled: bool = False
    _onlyonce: bool = False

    def init_plugin(self, config: dict = None):
        # 配置
        if config:
            self._enabled = config.get("enabled")
            self._onlyonce = config.get("onlyonce")

    def get_state(self) -> bool:
        return self._enabled

    @staticmethod
    def get_command() -> List[Dict[str, Any]]:
        return []

    def get_api(self) -> List[Dict[str, Any]]:
        return []

    def get_form(self) -> Tuple[List[dict], Dict[str, Any]]:
        """
        拼装插件配置页面
        """
        return [
            {
                'component': 'VForm',
                'content': [
                    {
                        'component': 'VRow',
                        'content': [
                            {
                                'component': 'VCol',
                                'props': {
                                    'cols': 12,
                                    'md': 4
                                },
                                'content': [
                                    {
                                        'component': 'VSwitch',
                                        'props': {
                                            'model': 'enabled',
                                            'label': '启用插件',
                                        }
                                    }
                                ]
                            },
                            {
                                'component': 'VCol',
                                'props': {
                                    'cols': 12,
                                    'md': 4
                                },
                                'content': [
                                    {
                                        'component': 'VSwitch',
                                        'props': {
                                            'model': 'onlyonce',
                                            'label': '立即运行一次',
                                        }
                                    }
                                ]
                            }
                        ]
                    }
                ]
            }
        ], {
            "enabled": False,
            "onlyonce": False
        }

    def get_page(self) -> List[dict]:
        """
        获取插件页面
        """
        # 获取所有站点数据
        site_data = self.__get_all_site_inviter_info()
        
        # 构建表格组件
        table_columns = [
            {"title": "站点名称", "key": "site_name", "width": 150},
            {"title": "邀请人", "key": "inviter_name", "width": 150},
            {"title": "邀请人ID", "key": "inviter_id", "width": 100},
            {"title": "邮箱", "key": "inviter_email", "width": 200},
            {"title": "获取时间", "key": "get_time", "width": 150}
        ]
        
        table_rows = []
        for site_name, inviter_info in site_data.items():
            table_rows.append({
                "site_name": site_name,
                "inviter_name": inviter_info.get("inviter_name", "-"),
                "inviter_id": inviter_info.get("inviter_id", "-"),
                "inviter_email": inviter_info.get("inviter_email", "-"),
                "get_time": inviter_info.get("get_time", "-")
            })
        
        return [
            {
                "component": "VCard",
                "props": {"class": "mb-4"},
                "content": [
                    {"component": "VCardTitle", "props": {"title": "PT站邀请人信息统计"}},
                    {
                        "component": "VCardText",
                        "content": [
                            {
                                "component": "VDataTable",
                                "props": {
                                    "columns": table_columns,
                                    "items": table_rows,
                                    "dense": True,
                                    "hide-default-footer": True,
                                    "fixed-header": True,
                                    "height": "600"
                                }
                            }
                        ]
                    }
                ]
            }
        ]

    def __get_all_site_inviter_info(self) -> Dict[str, Dict[str, Any]]:
        """
        获取所有站点的邀请人信息
        """
        site_data = {}
        
        # 获取所有活跃站点
        sites = SiteOper().list_active()
        if not sites:
            return site_data
        
        # 遍历所有站点
        for site in sites:
            try:
                # 根据站点域名获取邀请人信息
                domain = site.domain
                site_info = {
                    "cookie": site.cookie,
                    "ua": site.ua,
                    "proxy": site.proxy,
                    "timeout": site.timeout
                }
                
                inviter_info = {}
                
                # 根据站点域名调用不同的处理方法
                if "hdchina.org" in domain:
                    inviter_info = self.__get_hdchina_inviter_info(site_info)
                elif "chdbits.co" in domain:
                    inviter_info = self.__get_chdbits_inviter_info(site_info)
                elif "tjupt.org" in domain:
                    inviter_info = self.__get_tjupt_inviter_info(site_info)
                # 可以继续添加其他站点的处理方法
                
                if inviter_info:
                    # 添加获取时间
                    inviter_info["get_time"] = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
                    site_data[site.name] = inviter_info
            except Exception as e:
                logger.error(f"获取站点 {site.name} 邀请人信息失败: {e}")
        
        return site_data

    def __get_hdchina_inviter_info(self, site_info: Dict[str, Any]) -> Dict[str, Any]:
        """
        获取HDChina站点的邀请人信息
        """
        url = "https://hdchina.org/userdetails.php?id=0"
        cookie = site_info.get("cookie")
        ua = site_info.get("ua")
        proxy = site_info.get("proxy")
        timeout = site_info.get("timeout")
        
        res = RequestUtils(cookies=cookie, ua=ua, proxies=settings.PROXY if proxy else None, timeout=timeout).get_res(url=url)
        if not res or res.status_code != 200:
            return {}
        
        html = etree.HTML(res.text)
        if not html:
            return {}
        
        # 查找邀请人信息
        inviter_xpath = "//div[@class='userinfo']//li[contains(text(), '邀请人')]/text()"
        inviter_texts = html.xpath(inviter_xpath)
        if not inviter_texts:
            return {}
        
        # 解析邀请人信息
        inviter_text = inviter_texts[0]
        inviter_name = inviter_text.split("：")[1].strip() if "：" in inviter_text else ""
        
        # 查找邀请人ID和邮箱（如果隐私设置允许）
        inviter_id = ""
        inviter_email = ""
        
        # 尝试从邀请人链接中获取ID
        inviter_link_xpath = "//div[@class='userinfo']//li[contains(text(), '邀请人')]/a/@href"
        inviter_links = html.xpath(inviter_link_xpath)
        if inviter_links:
            inviter_link = inviter_links[0]
            if "id=" in inviter_link:
                inviter_id = inviter_link.split("id=")[1].split("&")[0]
                
                # 如果有邀请人ID，尝试获取其邮箱（如果隐私设置允许）
                if inviter_id:
                    inviter_email = self.__get_user_email("hdchina.org", inviter_id, site_info)
        
        return {
            "inviter_name": inviter_name,
            "inviter_id": inviter_id,
            "inviter_email": inviter_email
        }

    def __get_chdbits_inviter_info(self, site_info: Dict[str, Any]) -> Dict[str, Any]:
        """
        获取CHDBits站点的邀请人信息
        """
        url = "https://chdbits.co/userdetails.php?id=0"
        cookie = site_info.get("cookie")
        ua = site_info.get("ua")
        proxy = site_info.get("proxy")
        timeout = site_info.get("timeout")
        
        res = RequestUtils(cookies=cookie, ua=ua, proxies=settings.PROXY if proxy else None, timeout=timeout).get_res(url=url)
        if not res or res.status_code != 200:
            return {}
        
        html = etree.HTML(res.text)
        if not html:
            return {}
        
        # 查找邀请人信息
        inviter_xpath = "//div[@class='profile']//li[contains(text(), '邀请人')]"
        inviter_elements = html.xpath(inviter_xpath)
        if not inviter_elements:
            return {}
        
        # 解析邀请人信息
        inviter_name = ""
        inviter_id = ""
        
        inviter_element = inviter_elements[0]
        # 获取邀请人名称
        name_elements = inviter_element.xpath(".//a/text()")
        if name_elements:
            inviter_name = name_elements[0].strip()
        
        # 获取邀请人ID
        link_elements = inviter_element.xpath(".//a/@href")
        if link_elements:
            link = link_elements[0]
            if "id=" in link:
                inviter_id = link.split("id=")[1].split("&")[0]
                
                # 如果有邀请人ID，尝试获取其邮箱（如果隐私设置允许）
                inviter_email = self.__get_user_email("chdbits.co", inviter_id, site_info)
        
        return {
            "inviter_name": inviter_name,
            "inviter_id": inviter_id,
            "inviter_email": inviter_email
        }

    def __get_tjupt_inviter_info(self, site_info: Dict[str, Any]) -> Dict[str, Any]:
        """
        获取TJUPT站点的邀请人信息
        """
        url = "https://tjupt.org/userdetails.php?id=0"
        cookie = site_info.get("cookie")
        ua = site_info.get("ua")
        proxy = site_info.get("proxy")
        timeout = site_info.get("timeout")
        
        res = RequestUtils(cookies=cookie, ua=ua, proxies=settings.PROXY if proxy else None, timeout=timeout).get_res(url=url)
        if not res or res.status_code != 200:
            return {}
        
        html = etree.HTML(res.text)
        if not html:
            return {}
        
        # 查找邀请人信息
        inviter_xpath = "//div[@class='userinfo']//li[contains(text(), '邀请人')]"
        inviter_elements = html.xpath(inviter_xpath)
        if not inviter_elements:
            return {}
        
        # 解析邀请人信息
        inviter_name = ""
        inviter_id = ""
        
        inviter_element = inviter_elements[0]
        # 获取邀请人名称
        name_elements = inviter_element.xpath(".//a/text()")
        if name_elements:
            inviter_name = name_elements[0].strip()
        
        # 获取邀请人ID
        link_elements = inviter_element.xpath(".//a/@href")
        if link_elements:
            link = link_elements[0]
            if "id=" in link:
                inviter_id = link.split("id=")[1].split("&")[0]
                
                # 如果有邀请人ID，尝试获取其邮箱（如果隐私设置允许）
                inviter_email = self.__get_user_email("tjupt.org", inviter_id, site_info)
        
        return {
            "inviter_name": inviter_name,
            "inviter_id": inviter_id,
            "inviter_email": inviter_email
        }

    def __get_user_email(self, domain: str, user_id: str, site_info: Dict[str, Any]) -> str:
        """
        获取用户邮箱（如果隐私设置允许）
        """
        url = f"https://{domain}/userdetails.php?id={user_id}"
        cookie = site_info.get("cookie")
        ua = site_info.get("ua")
        proxy = site_info.get("proxy")
        timeout = site_info.get("timeout")
        
        res = RequestUtils(cookies=cookie, ua=ua, proxies=settings.PROXY if proxy else None, timeout=timeout).get_res(url=url)
        if not res or res.status_code != 200:
            return ""
        
        html = etree.HTML(res.text)
        if not html:
            return ""
        
        # 查找邮箱信息（不同站点的XPath可能不同）
        email_xpath = ""
        if "hdchina.org" in domain:
            email_xpath = "//div[@class='userinfo']//li[contains(text(), '邮箱')]/text()"
        elif "chdbits.co" in domain:
            email_xpath = "//div[@class='profile']//li[contains(text(), '邮箱')]/text()"
        elif "tjupt.org" in domain:
            email_xpath = "//div[@class='userinfo']//li[contains(text(), '邮箱')]/text()"
        
        if not email_xpath:
            return ""
        
        email_texts = html.xpath(email_xpath)
        if not email_texts:
            return ""
        
        # 解析邮箱信息
        email_text = email_texts[0]
        email = email_text.split("：")[1].strip() if "：" in email_text else ""
        return email

    def get_service(self) -> List[Dict[str, Any]]:
        return []

    def stop_service(self):
        pass
        