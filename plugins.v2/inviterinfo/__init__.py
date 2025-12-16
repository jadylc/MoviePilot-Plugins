from typing import Optional, Any, List, Dict, Tuple
from datetime import datetime, timedelta
import threading
from threading import Lock
from apscheduler.schedulers.background import BackgroundScheduler
from apscheduler.triggers.cron import CronTrigger
import pytz
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
    plugin_version = "1.20"
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
    _force_refresh: bool = False
    _sort_by: str = "site_name"
    _sort_direction: str = "asc"
    _notify: bool = False
    _cron: Optional[str] = None
    _scheduler: Optional[BackgroundScheduler] = None
    
    # 站点处理器
    _site_handlers: list = []

    def init_plugin(self, config: dict = None):
        logger.info("开始初始化PT站邀请人统计插件")
        # 初始化日志内容
        self._log_content = ""
        # 配置
        if config:
            logger.info(f"获取到插件配置: {config}")
            self._enabled = config.get("inviterinfo_enabled", False)
            self._onlyonce = config.get("inviterinfo_onlyonce", False)
            self._selected_sites = config.get("inviterinfo_selected_sites", [])
            self._force_refresh = config.get("inviterinfo_force_refresh", False)
            self._notify = config.get("inviterinfo_notify", False)
            self._cron = config.get("inviterinfo_cron")
            
            # 处理立即中断任务请求

            if self._onlyonce:
                logger.info("检测到onlyonce标志为True，开始在后台执行一次数据收集")
                # 定时服务
                self._scheduler = BackgroundScheduler(timezone=settings.TZ)
                logger.debug("立即运行一次开关已开启，将在3秒后执行刷新")
                self._scheduler.add_job(func=self.__get_all_site_inviter_info, trigger='date',
                                        run_date=datetime.now(pytz.timezone(settings.TZ)) + timedelta(seconds=3),
                                        name="PT站邀请人统计")
                # 重置onlyonce标志
                self._onlyonce = False
                # 更新配置到数据库
                self.update_config({
                    "inviterinfo_onlyonce": self._onlyonce,
                    "inviterinfo_enabled": self._enabled,
                    "inviterinfo_selected_sites": self._selected_sites,
                    "inviterinfo_force_refresh": self._force_refresh,
                    "inviterinfo_notify": self._notify,
                    "inviterinfo_cron": self._cron
                })
                # 启动任务
                if self._scheduler and self._scheduler.get_jobs():
                    self._scheduler.print_jobs()
                    self._scheduler.start()
        
        # 加载站点处理器
        logger.info("开始加载站点处理器")
        self._load_site_handlers()
        
        # 保存所有配置项到数据库
        self.update_config({
            "inviterinfo_enabled": self._enabled,
            "inviterinfo_onlyonce": self._onlyonce,
            "inviterinfo_selected_sites": self._selected_sites,
            "inviterinfo_force_refresh": self._force_refresh,
            "inviterinfo_notify": self._notify,
            "inviterinfo_cron": self._cron
        })
        
        logger.info("PT站邀请人统计插件初始化完成")

    def get_state(self) -> bool:
        return self._enabled

    @staticmethod
    def get_command() -> List[Dict[str, Any]]:
        return []

    def get_api(self) -> List[Dict[str, Any]]:
        return [
            {
                "path": "sort_table",
                "methods": ["POST"],
                "summary": "表格排序",
                "description": "根据指定字段对表格数据进行排序",
                "func": self.sort_table
            },
            {
                "path": "get_log",
                "methods": ["GET"],
                "summary": "获取执行日志",
                "description": "获取当前执行任务的日志内容",
                "func": self.get_log
            }
        ]

    
    def get_log(self):
        """
        获取执行日志
        """
        return {"log": getattr(self, '_log_content', '')}

    def _load_site_handlers(self):
        """
        加载站点处理器
        """
        try:
            logger.info("开始加载sites目录下的站点处理器")
            # 使用自定义ModuleLoader加载站点处理器
            self._site_handlers =  ModuleHelper.load('app.plugins.inviterinfo.sites',
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
        # 获取所有活跃站点
        managed_sites = SitesHelper().get_indexers()
        site_options = [
            {"title": site["name"], "value": str(site["id"])}
            for site in managed_sites 
            if site.get("name") and site.get("id")
        ]
        
        # 简化配置表单结构，确保插件系统能正确解析
        config_form = [
            {
                "component": "VForm",
                "on": {
                    "submit": "() => { this.$emit('submit'); }"
                },
                "content": [
                    {
                        "component": "VRow",
                        "content": [
                            {
                                "component": "VCol",
                                "props": {
                                    "cols": 12,
                                    "sm": 4
                                },
                                "content": [
                                    {
                                        "component": "VSwitch",
                                        "props": {
                                            "model": "inviterinfo_enabled",
                                            "label": "启用插件",
                                            "color": "primary"
                                        }
                                    }
                                ]
                            },
                            {
                                "component": "VCol",
                                "props": {
                                    "cols": 12,
                                    "sm": 4
                                },
                                "content": [
                                    {
                                        "component": "VSwitch",
                                        "props": {
                                            "model": "inviterinfo_onlyonce",
                                            "label": "立即运行一次",
                                            "color": "primary"
                                        }
                                    }
                                ]
                            },
                            {
                                "component": "VCol",
                                "props": {
                                    "cols": 12,
                                    "sm": 4
                                },
                                "content": [
                                    {
                                        "component": "VSwitch",
                                        "props": {
                                            "model": "inviterinfo_force_refresh",
                                            "label": "覆盖获取数据",
                                            "color": "primary"
                                        }
                                    }
                                ]
                            },
                            {
                                "component": "VCol",
                                "props": {
                                    "cols": 12,
                                    "sm": 4
                                },
                                "content": [
                                    {
                                        "component": "VSwitch",
                                        "props": {
                                            "model": "inviterinfo_notify",
                                            "label": "启用通知",
                                            "color": "primary"
                                        }
                                    }
                                ]
                            },
                            {
                                "component": "VCol",
                                "props": {
                                    "cols": 12
                                },
                                "content": [
                                    {
                                        "component": "VTextField",
                                        "props": {
                                            "model": "inviterinfo_cron",
                                            "label": "定时任务",
                                            "placeholder": "0 0 * * *",
                                            "variant": "outlined",
                                            "color": "primary",
                                            "hint": "定时执行任务的cron表达式，留空则关闭定时任务"
                                        }
                                    }
                                ]
                            }
                        ]
                    },
                    {
                        "component": "VRow",
                        "content": [
                            {
                                "component": "VCol",
                                "props": {
                                    "cols": 12
                                },
                                "content": [
                                    {
                                        "component": "VSelect",
                                        "props": {
                                            "model": "inviterinfo_selected_sites",
                                            "label": "选择要分析的PT站点",
                                            "items": site_options,
                                            "multiple": True,
                                            "clearable": True,
                                            "chips": True,
                                            "item_text": "title",
                                            "item_value": "value",
                                            "variant": "outlined",
                                            "color": "primary",
                                            "hint": "默认不选择任何站点表示分析所有站点",
                                            "persistent_hint": True
                                        }
                                    }
                                ]
                            }
                        ]
                    }
                ]
            }
        ]
        
        # 返回当前配置而不是默认配置，避免覆盖已保存的设置
        return config_form, {
            "inviterinfo_enabled": self._enabled,
            "inviterinfo_onlyonce": self._onlyonce,
            "inviterinfo_force_refresh": self._force_refresh,
            "inviterinfo_notify": self._notify,
            "inviterinfo_cron": self._cron,
            "inviterinfo_selected_sites": self._selected_sites
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
        
        # 获取当前日志信息
        log_content = getattr(self, '_log_content', '')
        
        # 构建表格数据
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
        
        # 根据当前排序设置对表格数据进行排序
        table_rows.sort(key=lambda x: x[self._sort_by].lower() if isinstance(x[self._sort_by], str) else x[self._sort_by], reverse=self._sort_direction == "desc")
        
        # 表头定义，包含排序字段映射
        headers = [
            {"text": "站点名称", "value": "site_name"},
            {"text": "邀请人", "value": "inviter_name"},
            {"text": "邀请人ID", "value": "inviter_id"},
            {"text": "邮箱", "value": "inviter_email"},
            {"text": "获取时间", "value": "get_time"}
        ]
        
        # 按邀请人统计站点数量
        inviter_stats = {}
        for site_name, inviter_info in site_data.items():
            inviter_name = inviter_info.get("inviter_name", "-")
            if inviter_name not in inviter_stats:
                inviter_stats[inviter_name] = 0
            inviter_stats[inviter_name] += 1
        
        # 转换为表格数据
        stats_rows = []
        for inviter_name, count in inviter_stats.items():
            stats_rows.append({
                "inviter_name": inviter_name,
                "site_count": count
            })
        
        # 按站点数量排序
        stats_rows.sort(key=lambda x: x["site_count"], reverse=True)
        
        return [
            {
                "component": "VCard",
                "props": {"class": "mb-4"},
                "content": [
                    {
                        "component": "VCardTitle",
                        "content": "PT站邀请人信息统计"
                    },
                    {
                        "component": "VCardText",
                        "content": [
                            {
                                "component": "VExpansionPanels",
                                "content": [
                                    {
                                        "component": "VExpansionPanel",
                                        "content": [
                                            {
                                                "component": "VExpansionPanelTitle",
                                                "content": "执行日志"
                                            },
                                            {"component": "VExpansionPanelText",
                                                "props": {
                                                    "class": "log-content"
                                                },
                                                "content": [
                                                    {
                                                        "component": "pre",
                                                        "props": {
                                                            "style": {
                                                                "max-height": "200px",
                                                                "overflow": "auto",
                                                                "background-color": "#f5f5f5",
                                                                "padding": "10px",
                                                                "border-radius": "4px"
                                                            },
                                                            "id": "inviterinfo-log"
                                                        },
                                                        "text": log_content
                                                    },
                                                    {
                                                        "component": "script",
                                                        "content": "\nfunction updateInviterInfoLog() {\n  invokePluginApi('inviterinfo', 'get_log').then(response => {\n    const logElement = document.getElementById('inviterinfo-log');\n    if (logElement && response && response.log) {\n      logElement.textContent = response.log;\n      logElement.scrollTop = logElement.scrollHeight;\n    }\n  });\n}\n\n// 初始调用一次\nupdateInviterInfoLog();\n\n// 设置定时器，每2秒更新一次\nconst logUpdateInterval = setInterval(updateInviterInfoLog, 2000);\n\n// 组件销毁时清除定时器\nwindow.addEventListener('beforeunload', () => {\n  clearInterval(logUpdateInterval);\n});\n"
                                                    }
                                                ]
                                            }
                                        ]
                                    }
                                ]
                            },
                            {
                                "component": "VTable",
                                "props": {
                                    "density": "compact",
                                    "hover": True
                                },
                                "content": [
                                    {
                                        "component": "thead",
                                        "content": [
                                            {
                                                "component": "tr",
                                                "content": [
                                                    {
                                                        "component": "th",
                                                        "props": {
                                                            "class": "sortable"
                                                        },
                                                        "content": [
                                                            {"component": "VBtn", "props": {
                                                                "text": True,
                                                                "size": "small"
                                                            }, "on": {
                                                                "click": "invokePluginApi('inviterinfo', 'sort_table', {{sort_by: 'site_name'}}).then(() => {{ this.$parent.$parent.$forceUpdate() }})"
                                                            }, "text": "站点名称"},
                                                            {"component": "VIcon", "props": {
                                                                "small": True,
                                                                "color": "primary"
                                                            }, "text": "mdi-sort"}
                                                        ]
                                                    },
                                                    {
                                                        "component": "th",
                                                        "props": {
                                                            "class": "sortable"
                                                        },
                                                        "content": [
                                                            {"component": "VBtn", "props": {
                                                                "text": True,
                                                                "size": "small"
                                                            }, "on": {
                                                                "click": "invokePluginApi('inviterinfo', 'sort_table', {{sort_by: 'inviter_name'}}).then(() => {{ this.$parent.$parent.$forceUpdate() }})"
                                                            }, "text": "邀请人"},
                                                            {"component": "VIcon", "props": {
                                                                "small": True,
                                                                "color": "primary"
                                                            }, "text": "mdi-sort"}
                                                        ]
                                                    },
                                                    {
                                                        "component": "th",
                                                        "props": {
                                                            "class": "sortable"
                                                        },
                                                        "content": [
                                                            {"component": "VBtn", "props": {
                                                                "text": True,
                                                                "size": "small"
                                                            }, "on": {
                                                                "click": "invokePluginApi('inviterinfo', 'sort_table', {{sort_by: 'inviter_id'}}).then(() => {{ this.$parent.$parent.$forceUpdate() }})"
                                                            }, "text": "邀请人ID"},
                                                            {"component": "VIcon", "props": {
                                                                "small": True,
                                                                "color": "primary"
                                                            }, "text": "mdi-sort"}
                                                        ]
                                                    },
                                                    {
                                                        "component": "th",
                                                        "props": {
                                                            "class": "sortable"
                                                        },
                                                        "content": [
                                                            {"component": "VBtn", "props": {
                                                                "text": True,
                                                                "size": "small"
                                                            }, "on": {
                                                                "click": "invokePluginApi('inviterinfo', 'sort_table', {{sort_by: 'inviter_email'}}).then(() => {{ this.$parent.$parent.$forceUpdate() }})"
                                                            }, "text": "邮箱"},
                                                            {"component": "VIcon", "props": {
                                                                "small": True,
                                                                "color": "primary"
                                                            }, "text": "mdi-sort"}
                                                        ]
                                                    },
                                                    {
                                                        "component": "th",
                                                        "props": {
                                                            "class": "sortable"
                                                        },
                                                        "content": [
                                                            {"component": "VBtn", "props": {
                                                                "text": True,
                                                                "size": "small"
                                                            }, "on": {
                                                                "click": "invokePluginApi('inviterinfo', 'sort_table', {{sort_by: 'get_time'}}).then(() => {{ this.$parent.$parent.$forceUpdate() }})"
                                                            }, "text": "获取时间"},
                                                            {"component": "VIcon", "props": {
                                                                "small": True,
                                                                "color": "primary"
                                                            }, "text": "mdi-sort"}
                                                        ]
                                                    }
                                                ]
                                            }
                                        ]
                                    },
                                    {
                                        "component": "tbody",
                                        "content": [
                                            {
                                                "component": "tr",
                                                "content": [
                                                    {
                                                        "component": "td",
                                                        "text": row["site_name"]
                                                    },
                                                    {
                                                        "component": "td",
                                                        "text": row["inviter_name"]
                                                    },
                                                    {
                                                        "component": "td",
                                                        "text": row["inviter_id"]
                                                    },
                                                    {
                                                        "component": "td",
                                                        "text": row["inviter_email"]
                                                    },
                                                    {
                                                        "component": "td",
                                                        "text": row["get_time"]
                                                    }
                                                ]
                                            } for row in table_rows
                                        ]
                                    }
                                ]
                            },
                            {
                                "component": "VTable",
                                "props": {
                                    "density": "compact",
                                    "hover": True,
                                    "class": "mt-4"
                                },
                                "content": [
                                    {
                                        "component": "thead",
                                        "content": [
                                            {
                                                "component": "tr",
                                                "content": [
                                                    {
                                                        "component": "th",
                                                        "text": "邀请人"
                                                    },
                                                    {
                                                        "component": "th",
                                                        "text": "邀请站点数量"
                                                    }
                                                ]
                                            }
                                        ]
                                    },
                                    {
                                        "component": "tbody",
                                        "content": [
                                            {
                                                "component": "tr",
                                                "content": [
                                                    {
                                                        "component": "td",
                                                        "text": row["inviter_name"]
                                                    },
                                                    {
                                                        "component": "td",
                                                        "text": str(row["site_count"])
                                                    }
                                                ]
                                            } for row in stats_rows
                                        ]
                                    }
                                ]
                            }
                        ]
                    }
                ]
            }
        ]

    def __get_all_site_inviter_info(self, force_refresh: bool = False) -> Dict[str, Dict[str, Any]]:
        """
        获取所有站点的邀请人信息
        :param force_refresh: 是否强制刷新所有数据，即使已存在
        """
        start_time = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        log_msg = f"[{start_time}] === 开始获取所有站点的邀请人信息 ===\n"
        logger.info(log_msg.strip())
        
        # 更新日志内容
        self._log_content = log_msg
        
        # 先加载已有的数据，避免清除未勾选站点的历史数据
        site_data = self.__load_site_data()
        initial_count = len(site_data)
        
        log_msg = f"[{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}] 已加载 {initial_count} 个站点的历史数据\n"
        logger.info(log_msg.strip())
        self._log_content += log_msg
        
        # 获取所有活跃站点
        try:
            managed_sites = SitesHelper().get_indexers()
            log_msg = f"[{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}] 成功获取到 {len(managed_sites)} 个活跃站点\n"
            logger.info(log_msg.strip())
            self._log_content += log_msg
            
            if not managed_sites:
                log_msg = f"[{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}] 没有找到活跃站点，直接返回\n"
                logger.info(log_msg.strip())
                self._log_content += log_msg
                return site_data
            # 转换为Site对象格式以兼容现有代码
            sites = []
            for site_info in managed_sites:
                # 创建一个类似Site对象的实例
                site_obj = type('Site', (), {
                    'id': int(site_info.get('id', 0)),
                    'name': site_info.get('name', ''),
                    'url': site_info.get('url', ''),
                    'cookie': site_info.get('cookie', ''),
                    'ua': site_info.get('ua', ''),
                    'proxy': site_info.get('proxy', ''),
                    'timeout': site_info.get('timeout', 20)
                })()
                sites.append(site_obj)
        except Exception as e:
            logger.error(f"获取活跃站点列表失败: {str(e)}")
            logger.exception(e)
            return site_data
        
        # 如果没有加载到站点处理器，尝试重新加载
        if not self._site_handlers:
            log_msg = f"[{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}] 没有加载到站点处理器，尝试重新加载\n"
            logger.info(log_msg.strip())
            self._log_content += log_msg
            try:
                self._load_site_handlers()
                log_msg = f"[{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}] 成功加载 {len(self._site_handlers)} 个站点处理器\n"
                logger.info(log_msg.strip())
                self._log_content += log_msg
            except Exception as e:
                log_msg = f"[{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}] 重新加载站点处理器失败: {str(e)}\n"
                logger.error(log_msg.strip())
                self._log_content += log_msg
        
        # 遍历所有站点
        log_msg = f"[{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}] 用户选择的站点列表: {self._selected_sites}\n"
        logger.info(log_msg.strip())
        self._log_content += log_msg
        
        processed_count = 0
        success_count = 0
        skip_count = 0
        error_count = 0
        
        # 如果未选择任何站点，将处理所有站点（默认全选）
        if not self._selected_sites:
            log_msg = f"[{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}] 未选择任何站点，将处理所有站点\n"
            logger.info(log_msg.strip())
            self._log_content += log_msg
        
        for site in sites:
            try:
                logger.info(f"=== 开始处理站点: {site.name} (ID: {site.id}) ===")
                log_msg = f"[{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}] 开始处理站点: {site.name}\n"
                logger.info(log_msg.strip())
                self._log_content += log_msg
                
                # 检查站点是否在用户选择的站点列表中（如果_selected_sites为空，则处理所有站点）
                if self._selected_sites and str(site.id) not in self._selected_sites:
                    logger.info(f"站点 {site.name} 不在用户选择的站点列表中，保持原有数据")
                    log_msg = f"[{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}] 站点 {site.name} 不在选择列表中，跳过\n"
                    logger.info(log_msg.strip())
                    self._log_content += log_msg
                    continue
                    
                # 检查是否已有数据且不需要强制刷新
                if not force_refresh and site.name in site_data:
                    logger.info(f"站点 {site.name} 已有邀请人数据，跳过获取")
                    log_msg = f"[{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}] 站点 {site.name} 已有数据，跳过获取\n"
                    logger.info(log_msg.strip())
                    self._log_content += log_msg
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
                logger.debug(f"构建的站点信息: {site_info}")
                
                logger.info(f"开始获取站点 {site.name} 的邀请人信息")
                
                # 查找匹配的站点处理器
                matched_handler = None
                try:
                    logger.info(f"开始查找匹配的站点处理器，共有 {len(self._site_handlers)} 个处理器可用")
                    log_msg = f"[{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}] 查找站点处理器...\n"
                    logger.info(log_msg.strip())
                    self._log_content += log_msg
                    matched_handler = self.__build_class(site.url)
                    if matched_handler:
                        logger.info(f"成功获取站点处理器实例: {matched_handler.__class__.__name__}")
                        log_msg = f"[{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}] 成功获取站点处理器: {matched_handler.__class__.__name__}\n"
                        logger.info(log_msg.strip())
                        self._log_content += log_msg
                except Exception as ex:
                    logger.error(f"查找站点处理器失败: {str(ex)}")
                    log_msg = f"[{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}] 查找站点处理器失败: {str(ex)}\n"
                    logger.info(log_msg.strip())
                    self._log_content += log_msg
                    logger.exception(ex)

                # 获取邀请人信息
                inviter_info = None
                if matched_handler:
                    try:
                        logger.info(f"使用处理器 {matched_handler.__class__.__name__} 获取邀请人信息")
                        inviter_info = matched_handler.get_inviter_info(site_info)
                        logger.info(f"成功获取站点 {site.name} 的邀请人信息")
                        logger.debug(f"邀请人信息内容: {inviter_info}")
                    except Exception as ex:
                        logger.error(f"获取邀请人信息失败: {str(ex)}")
                        logger.exception(ex)
                else:
                    logger.info(f"站点 {site.name} 暂不支持邀请人信息获取")
                    
                # 保存邀请人信息
                if inviter_info is not None:
                    logger.info(f"开始保存站点 {site.name} 的邀请人信息")
                    try:
                        site_data_entry = {
                            "inviter_name": inviter_info.get("inviter_name", "-"),
                            "inviter_id": inviter_info.get("inviter_id", "-"),
                            "inviter_email": inviter_info.get("inviter_email", "-"),
                            "get_time": datetime.now().strftime("%Y-%m-%d %H:%M:%S")
                        }
                        site_data[site.name] = site_data_entry
                        logger.info(f"成功保存站点 {site.name} 的邀请人信息")
                        logger.debug(f"保存的信息: {site_data_entry}")
                        # 保存到持久化存储
                        self.__save_site_data(site_data)
                    except Exception as ex:
                        logger.error(f"保存邀请人信息失败: {str(ex)}")
                        logger.exception(ex)
                else:
                    logger.info(f"站点 {site.name} 的邀请人信息为空，不保存")
                    
            except Exception as e:
                logger.error(f"处理站点 {site.name} 时发生未预期的错误: {str(e)}")
                logger.exception(e)
                logger.info(f"继续处理下一个站点")
                continue
        
        # 统计本次获取的站点数量
        final_count = len(site_data)
        new_count = final_count - initial_count
        
        logger.info(f"=== 所有站点处理完成，共获取到 {final_count} 个站点的邀请人信息 ====")
        
        # 发送通知（如果启用）
        if self._notify:
            try:
                if new_count > 0:
                    # 生成邀请人统计数据
                    inviter_stats = {}
                    for site_name, inviter_info in site_data.items():
                        inviter_name = inviter_info.get("inviter_name", "-")
                        if inviter_name not in inviter_stats:
                            inviter_stats[inviter_name] = 0
                        inviter_stats[inviter_name] += 1
                    
                    # 转换为表格数据并排序
                    stats_rows = []
                    for inviter_name, count in inviter_stats.items():
                        stats_rows.append({
                            "inviter_name": inviter_name,
                            "site_count": count
                        })
                    stats_rows.sort(key=lambda x: x["site_count"], reverse=True)
                    
                    # 格式化统计数据为表格
                    stats_text = "\n" + "邀请人统计数据:\n"
                    stats_text += "-" * 25 + "\n"
                    stats_text += f'{"邀请人":<15} {"站点数量":>8}\n'
                    stats_text += "-" * 25 + "\n"
                    for row in stats_rows:
                        stats_text += f"{row['inviter_name']:<15} {row['site_count']:>8}\n"
                    
                    title = "【PT站邀请人统计】数据收集完成"
                    text = f"成功获取 {new_count} 个站点的邀请人信息\n当前共收集 {final_count} 个站点的数据" + stats_text
                    self.post_message(
                        mtype=NotificationType.SiteMessage,
                        title=title,
                        text=text
                    )
            except Exception as e:
                logger.error(f"发送通知失败: {str(e)}")
        
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

    def sort_table(self, sort_by: str):
        """
        根据指定字段对表格数据进行排序
        :param sort_by: 排序字段
        """
        logger.info(f"收到排序请求：{sort_by}")
        
        # 如果当前排序字段与请求的排序字段相同，则切换排序方向
        if self._sort_by == sort_by:
            self._sort_direction = "desc" if self._sort_direction == "asc" else "asc"
        else:
            # 否则，设置新的排序字段，并默认使用升序
            self._sort_by = sort_by
            self._sort_direction = "asc"
        
        logger.info(f"排序字段：{self._sort_by}，排序方向：{self._sort_direction}")
        
        # 重新加载页面数据（通过返回排序后的表格数据，插件系统会自动更新页面）
        return {
            "sort_by": self._sort_by,
            "sort_direction": self._sort_direction
        }

    def get_service(self) -> List[Dict[str, Any]]:
        # 配置定时任务
        if self._enabled and self._cron:
            try:
                # 检查是否为5位cron表达式
                if str(self._cron).strip().count(" ") == 4:
                    return [{
                        "id": "inviterinfo",
                        "name": "PT站邀请人统计",
                        "trigger": CronTrigger.from_crontab(self._cron),
                        "func": self.__get_all_site_inviter_info,
                        "kwargs": {}
                    }]
                else:
                    logger.error("cron表达式格式错误")
                    return []
            except Exception as err:
                logger.error(f"定时任务配置错误：{str(err)}")
                return []
        return []
        # 初始化调度器
        self._scheduler = BackgroundScheduler(timezone=settings.TZ)




    def stop_service(self):
        """
        停止插件服务
        """
        try:
            if hasattr(self, "_scheduler") and self._scheduler:
                self._scheduler.remove_all_jobs()
                if self._scheduler.running:
                    self._scheduler.shutdown()
                self._scheduler = None
                logger.info("定时任务调度器已关闭")
        except Exception as e:
            logger.error(f"关闭定时任务调度器失败: {str(e)}")
            logger.exception(e)


    def __build_class(self, site_url) -> Any:
        for site_handler in self._site_handlers:
            try:
                if site_handler.match(site_url):
                    return site_handler
            except Exception as e:
                logger.error("站点模块加载失败：%s" % str(e))
        return None
        
