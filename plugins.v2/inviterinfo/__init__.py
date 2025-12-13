from typing import Optional, Any, List, Dict, Tuple
from datetime import datetime
from threading import Lock

from app import schemas
from app.core.config import settings
from app.core.event import eventmanager, Event
from app.db.models.siteuserdata import SiteUserData
from app.db.site_oper import SiteOper
from app.helper.module import ModuleHelper
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
    plugin_desc = "统计所有PT站的上家信息，包括邀请人信息和邮箱（如果隐私设置允许）"
    # 插件图标
    plugin_icon = "user.png"
    # 插件版本
    plugin_version = "1.3"
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
    _selected_sites: list = []
    _abort_flag: bool = False
    
    # 站点处理器
    _site_handlers: list = []

    def init_plugin(self, config: dict = None):
        logger.info("开始初始化PT站邀请人统计插件")
        # 配置
        if config:
            logger.info(f"获取到插件配置: {config}")
            self._enabled = config.get("enabled")
            self._onlyonce = config.get("onlyonce")
            self._selected_sites = config.get("selected_sites", [])
            
            # 处理立即中断任务请求
            aborttask = config.get("aborttask")
            if aborttask:
                logger.info("检测到aborttask标志为True，触发任务中断")
                self.abort_run()
            
            # 如果onlyonce为True，执行一次数据收集
            if self._onlyonce:
                logger.info("检测到onlyonce标志为True，开始执行一次数据收集")
                self.__get_all_site_inviter_info()
                logger.info("数据收集完成")
                # 重置onlyonce标志
                self._onlyonce = False
        
        # 加载站点处理器
        logger.info("开始加载站点处理器")
        self._load_site_handlers()
        logger.info("PT站邀请人统计插件初始化完成")

    def get_state(self) -> bool:
        return self._enabled

    @staticmethod
    def get_command() -> List[Dict[str, Any]]:
        return []

    def get_api(self) -> List[Dict[str, Any]]:
        return [
            {
                "path": "abort_run",
                "methods": ["GET"],
                "summary": "中止邀请人信息收集",
                "description": "中止正在进行的PT站邀请人信息收集任务",
                "func": self.abort_run
            }
        ]
    
    def abort_run(self):
        """
        设置中止标志，终止正在进行的邀请人信息收集
        """
        with lock:
            self._abort_flag = True
        logger.info("收到中止信号，将终止邀请人信息收集")

    def _load_site_handlers(self):
        """
        加载站点处理器
        """
        try:
            logger.info("开始加载sites目录下的站点处理器")
            # 使用ModuleHelper加载sites目录下的所有站点处理器
            self._site_handlers = ModuleHelper.load('app.plugins.inviterinfo.sites',
                                                   filter_func=lambda _, obj: hasattr(obj, 'match'))
            logger.info(f"成功加载 {len(self._site_handlers)} 个站点处理器")
            # 记录每个加载的处理器
            for handler_cls in self._site_handlers:
                logger.info(f"加载站点处理器: {handler_cls.__name__}")
        except Exception as e:
            logger.error(f"加载站点处理器失败: {e}")
            logger.exception(e)
            self._site_handlers = []

    def get_form(self) -> Tuple[List[dict], Dict[str, Any]]:
        """
        拼装插件配置页面
        """
        logger.info("开始生成插件配置表单")
        # 获取所有活跃站点
        sites = SiteOper().list_active()
        logger.info(f"获取到 {len(sites)} 个活跃站点")
        site_options = []
        for site in sites:
            site_option = {
                "title": site.name,
                "value": str(site.id)
            }
            site_options.append(site_option)
            logger.info(f"添加站点选项: {site_option}")
        
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
                                            'model': 'aborttask',
                                            'label': '立即中断任务',
                                        }
                                    }
                                ]
                            }
                        ]
                    },
                    {
                        'component': 'VRow',
                        'content': [
                            {
                                'component': 'VCol',
                                'props': {
                                    'cols': 12
                                },
                                'content': [
                                    {
                                        'component': 'VSelect',
                                        'props': {
                                            'model': 'selected_sites',
                                            'label': '选择要分析的PT站点',
                                            'items': site_options,
                                            'multiple': True,
                                            'clearable': True,
                                            'chips': True,
                                            'small_chips': True,
                                            'hide_details': True,
                                            'item_text': 'title',
                                            'item_value': 'value'
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
            "onlyonce": False,
            "aborttask": False,
            "selected_sites": []
        }

    def get_page(self) -> List[dict]:
        """
        获取插件页面
        """
        logger.info("开始生成插件页面")
        # 获取所有站点数据（仅显示已有的数据，不自动收集）
        site_data = self.__load_site_data()
        logger.info(f"从持久化存储中加载了 {len(site_data)} 条站点数据")
        logger.info("页面加载完成，不自动获取站点邀请人信息")
        
        # 构建表格组件
        table_columns = [
            {"title": "站点名称", "key": "site_name", "width": 150},
            {"title": "邀请人", "key": "inviter_name", "width": 150},
            {"title": "邀请人ID", "key": "inviter_id", "width": 100},
            {"title": "邮箱", "key": "inviter_email", "width": 200},
            {"title": "获取时间", "key": "get_time", "width": 150}
        ]
        logger.info(f"构建表格，包含 {len(table_columns)} 列")
        
        table_rows = []
        for site_name, inviter_info in site_data.items():
            table_row = {
                "site_name": site_name,
                "inviter_name": inviter_info.get("inviter_name", "-"),
                "inviter_id": inviter_info.get("inviter_id", "-"),
                "inviter_email": inviter_info.get("inviter_email", "-"),
                "get_time": inviter_info.get("get_time", "-")
            }
            table_rows.append(table_row)
            logger.info(f"添加表格行: {table_row}")
        logger.info(f"构建表格，包含 {len(table_rows)} 行数据")
        
        return [
            {
                "component": "VCard",
                "props": {"class": "mb-4"},
                "content": [
                    {"component": "VCardTitle", "props": {"title": "PT站邀请人信息统计"}},
                    {
                        "component": "VCardActions",
                        "props": {"class": "px-4 py-2"},
                        "content": [
                            {
                                "component": "VBtn",
                                "props": {
                                    "color": "error",
                                    "text": True,
                                    "onClick": "invokePluginApi('inviterinfo', 'abort_run')"
                                },
                                "content": "中止运行"
                            }
                        ]
                    },
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
        logger.info("开始获取所有站点的邀请人信息")
        site_data = {}
        
        # 获取所有活跃站点
        sites = SiteOper().list_active()
        logger.info(f"获取到 {len(sites)} 个活跃站点")
        if not sites:
            logger.info("没有找到活跃站点，直接返回")
            return site_data
        
        # 如果没有加载到站点处理器，尝试重新加载
        if not self._site_handlers:
            logger.info("没有加载到站点处理器，尝试重新加载")
            self._load_site_handlers()
        
        # 遍历所有站点
        logger.info(f"用户选择的站点列表: {self._selected_sites}")
        for site in sites:
            # 检查是否收到中止信号
            with lock:
                abort_flag = self._abort_flag
            if abort_flag:
                logger.info("中止标志已设置，停止站点信息收集")
                # 重置中止标志
                with lock:
                    self._abort_flag = False
                break
            try:
                logger.info(f"开始处理站点: {site.name} (ID: {site.id})")
                # 检查站点是否在用户选择的站点列表中
                if self._selected_sites and str(site.id) not in self._selected_sites:
                    logger.info(f"站点 {site.name} 不在用户选择的站点列表中，跳过")
                    continue
                    
                # 构建站点信息
                site_info = {
                    "id": site.id,
                    "name": site.name,
                    "url": site.url,
                    "cookie": site.cookie,
                    "ua": site.ua,
                    "proxy": site.proxy,
                    "timeout": site.timeout or 20
                }
                logger.info(f"构建站点信息: {site_info}")
                
                logger.info(f"开始获取站点 {site.name} 的邀请人信息")
                
                # 查找匹配的站点处理器
                matched_handler = None
                logger.info(f"开始查找匹配的站点处理器，共有 {len(self._site_handlers)} 个处理器")
                for handler_cls in self._site_handlers:
                    handler = handler_cls()
                    logger.info(f"尝试处理器: {handler_cls.__name__}")
                    if handler.match(site.url):
                        matched_handler = handler
                        logger.info(f"找到匹配的站点处理器: {handler_cls.__name__}")
                        break
                
                # 如果没有找到匹配的处理器，尝试使用NexusPHP通用处理器
                if not matched_handler:
                    # 检查是否收到中止信号
                    with lock:
                        abort_flag = self._abort_flag
                    if abort_flag:
                        logger.info("中止标志已设置，停止站点信息收集")
                        # 重置中止标志
                        with lock:
                            self._abort_flag = False
                        break
                    logger.info(f"没有找到匹配的站点处理器，尝试检查是否为NexusPHP站点")
                    from app.plugins.inviterinfo.sites.nexusphp import NexusPHPInviterInfoHandler
                    # 检查是否是NexusPHP站点
                    if self.__is_nexusphp_site(site_info):
                        matched_handler = NexusPHPInviterInfoHandler()
                        logger.info(f"站点 {site.name} 使用NexusPHP通用处理器")
                    else:
                        logger.info(f"站点 {site.name} 不是NexusPHP站点，无法处理")
                
                # 获取邀请人信息
                inviter_info = None
                if matched_handler:
                    # 检查是否收到中止信号
                    with lock:
                        abort_flag = self._abort_flag
                    if abort_flag:
                        logger.info("中止标志已设置，停止站点信息收集")
                        # 重置中止标志
                        with lock:
                            self._abort_flag = False
                        break
                    logger.info(f"使用处理器 {matched_handler.__class__.__name__} 获取邀请人信息")
                    inviter_info = matched_handler.get_inviter_info(site_info)
                    logger.info(f"成功获取站点 {site.name} 的邀请人信息: {inviter_info}")
                else:
                    logger.info(f"站点 {site.name} 暂不支持邀请人信息获取")
                    
                # 保存邀请人信息
                if inviter_info is not None:
                    logger.info(f"开始保存站点 {site.name} 的邀请人信息")
                    site_data_entry = {
                        "inviter_name": inviter_info.get("inviter_name", "-"),
                        "inviter_id": inviter_info.get("inviter_id", "-"),
                        "inviter_email": inviter_info.get("inviter_email", "-"),
                        "get_time": datetime.now().strftime("%Y-%m-%d %H:%M:%S")
                    }
                    site_data[site.name] = site_data_entry
                    logger.info(f"成功保存站点 {site.name} 的邀请人信息: {site_data_entry}")
                    # 保存到持久化存储
                    self.__save_site_data(site_data)
                else:
                    logger.info(f"站点 {site.name} 的邀请人信息为None，不保存")
                    
            except Exception as e:
                logger.error(f"获取站点 {site.name} 的邀请人信息失败: {e}")
                continue
        
        return site_data
    
    def __save_site_data(self, site_data: dict):
        """
        保存站点数据到JSON文件
        :param site_data: 站点数据
        """
        import json
        import os
        try:
            # 获取插件目录
            plugin_dir = os.path.dirname(os.path.abspath(__file__))
            data_file = os.path.join(plugin_dir, "site_data.json")
            logger.info(f"开始保存站点数据到 {data_file}")
            
            with open(data_file, "w", encoding="utf-8") as f:
                json.dump(site_data, f, ensure_ascii=False, indent=2)
            logger.info(f"成功保存站点数据到 {data_file}")
        except Exception as e:
            logger.error(f"保存站点数据失败: {e}")
            logger.exception(e)
    
    def __load_site_data(self) -> dict:
        """
        从JSON文件加载站点数据
        :return: 站点数据
        """
        import json
        import os
        try:
            # 获取插件目录
            plugin_dir = os.path.dirname(os.path.abspath(__file__))
            data_file = os.path.join(plugin_dir, "site_data.json")
            logger.info(f"开始从 {data_file} 加载站点数据")
            
            if not os.path.exists(data_file):
                logger.info(f"数据文件 {data_file} 不存在，返回空数据")
                return {}
            
            with open(data_file, "r", encoding="utf-8") as f:
                site_data = json.load(f)
            logger.info(f"成功从 {data_file} 加载站点数据")
            return site_data
        except Exception as e:
            logger.error(f"加载站点数据失败: {e}")
            logger.exception(e)
            return {}
    
    def __is_nexusphp_site(self, site_info: dict) -> bool:
        """
        判断站点是否为NexusPHP站点
        :param site_info: 站点信息
        :return: 是否为NexusPHP站点
        """
        logger.info(f"开始判断站点 {site_info.get('name')} 是否为NexusPHP站点")
        try:
            site_url = site_info.get("url")
            if not site_url:
                logger.info("站点URL为空，无法判断是否为NexusPHP站点")
                return False
                
            # 尝试访问用户详情页
            user_url = f"{site_url}/userdetails.php?id=0"
            logger.info(f"尝试访问用户详情页: {user_url}")
            cookie = site_info.get("cookie")
            ua = site_info.get("ua")
            proxy = site_info.get("proxy")
            timeout = site_info.get("timeout", 20)
            
            headers = {
                "User-Agent": ua,
                "Cookie": cookie
            }
            logger.info(f"使用Headers: {headers}")
            
            res = RequestUtils(headers=headers,
                               proxies=settings.PROXY if proxy else None,
                               timeout=timeout).get_res(url=user_url)
            
            if res:
                logger.info(f"获取页面状态码: {res.status_code}")
                if res.status_code == 200:
                    # 检查页面是否包含NexusPHP特征
                    logger.info("检查页面是否包含NexusPHP特征")
                    page_content = res.text
                    
                    # 定义NexusPHP常见特征
                    nexusphp_features = [
                        "NexusPHP",
                        "Powered by",
                        "userdetails",
                        "rowhead",
                        "userinfo",
                        "profile",
                        "outer",
                        "userdetails.php",
                        "takelogin.php",
                        "index.php",
                        "torrents.php",
                        "forums.php",
                        "my.php",
                        "nexusphp",
                        "// NexusPHP",
                        "var SITENAME",
                        "var BASEURL",
                        "var USERNAME",
                        "class='userdetails'",
                        "class='rowhead'",
                        "class='userinfo'",
                        "class='profile'"
                    ]
                    
                    # 计算匹配的特征数量
                    matched_features = []
                    for feature in nexusphp_features:
                        if feature in page_content:
                            matched_features.append(feature)
                    
                    logger.info(f"匹配到 {len(matched_features)} 个NexusPHP特征: {matched_features}")
                    
                    # 判断是否为NexusPHP站点的逻辑
                    # 1. 必须包含userdetails相关特征
                    has_userdetails = any(feature in ["userdetails", "userdetails.php", "class='userdetails'"] for feature in matched_features)
                    # 2. 至少包含其他3个以上的NexusPHP特征
                    has_enough_features = len(matched_features) >= 4
                    
                    if has_userdetails and has_enough_features:
                        logger.info(f"站点 {site_info.get('name')} 是NexusPHP站点")
                        return True
                    else:
                        logger.info(f"站点 {site_info.get('name')} 不是NexusPHP站点")
                        logger.info(f"判断条件: has_userdetails={has_userdetails}, has_enough_features={has_enough_features}")
                        return False
                else:
                    logger.info(f"获取页面失败，状态码: {res.status_code}")
                    # 如果用户详情页无法访问，尝试访问首页
                    logger.info("尝试访问站点首页")
                    try:
                        home_url = site_url.rstrip("/")
                        res = RequestUtils(headers=headers,
                                          proxies=settings.PROXY if proxy else None,
                                          timeout=timeout).get_res(url=home_url)
                        if res and res.status_code == 200:
                            page_content = res.text
                            # 检查首页是否包含NexusPHP特征
                            if any(feature in page_content for feature in ["NexusPHP", "Powered by", "var SITENAME", "var BASEURL"]):
                                logger.info(f"从首页判断站点 {site_info.get('name')} 是NexusPHP站点")
                                return True
                    except Exception as e:
                        logger.error(f"访问首页失败: {e}")
                    return False
            else:
                logger.info("获取页面无响应")
                return False
        except Exception as e:
            logger.error(f"判断站点类型失败: {e}")
            logger.exception(e)
            return False

    def get_service(self) -> List[Dict[str, Any]]:
        return []

    def stop_service(self):
        pass
        
