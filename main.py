import random
import time
import asyncio
import os
import json
from typing import List, Dict, Any, Optional
from astrbot.api.event import filter, AstrMessageEvent, MessageChain
from astrbot.api.star import Context, Star
from astrbot.api import AstrBotConfig
import astrbot.api.message_components as Comp
from astrbot.core.utils.astrbot_path import get_astrbot_data_path

class BrickPlugin(Star):
    def __init__(self, context: Context, config: AstrBotConfig):
        super().__init__(context)
        self.config = config
        self.data_dir = get_astrbot_data_path() / "plugin_data" / "brick_plugin"
        self.data_dir.mkdir(parents=True, exist_ok=True)
        self.data_file = self.data_dir / "brick_data.json"
        self.user_data = self._load_data()
        self.burning_status = {}  # {guild_id: {user_id: {"count": 0, "target": 0}}}
        self.working_status = {}  # {guild_id: {user_id: {"count": 0, "target": 0}}}
        self.last_steal_time = {} # {user_id: timestamp}
        self.blacklist_confirm = set() # 用户确认进入黑名单

    def _load_data(self):
        if self.data_file.exists():
            with open(self.data_file, 'r', encoding='utf-8') as f:
                return json.load(f)
        return {"users": {}, "user_blacklist": self.config.get("user_blacklist", []), "group_blacklist": self.config.get("group_blacklist", [])}

    def _save_data(self):
        with open(self.data_file, 'w', encoding='utf-8') as f:
            json.dump(self.user_data, f, ensure_ascii=False, indent=4)

    def _get_user(self, guild_id: str, user_id: str):
        key = f"{guild_id}:{user_id}"
        if key not in self.user_data["users"]:
            self.user_data["users"][key] = {
                "brick": 0,
                "last_slap": 0,
                "last_check": "",
                "is_new": True
            }
        return self.user_data["users"][key]

    def _is_blacklisted(self, event: AstrMessageEvent):
        user_id = event.get_sender_id()
        group_id = event.get_group_id()
        if self.config.get("enable_user_blacklist") and user_id in self.user_data.get("user_blacklist", []):
            return True
        if self.config.get("enable_group_blacklist") and group_id and group_id in self.user_data.get("group_blacklist", []):
            return True
        return False

    @filter.on_astrbot_loaded()
    async def on_loaded(self):
        # 同步配置中的黑名单到本地数据
        self.user_data["user_blacklist"] = list(set(self.user_data.get("user_blacklist", []) + self.config.get("user_blacklist", [])))
        self.user_data["group_blacklist"] = list(set(self.user_data.get("group_blacklist", []) + self.config.get("group_blacklist", [])))
        self._save_data()

    @filter.event_message_type(filter.EventMessageType.ALL)
    async def handle_all_messages(self, event: AstrMessageEvent):
        if self._is_blacklisted(event):
            event.stop_event()
            return

        guild_id = event.get_group_id()
        user_id = event.get_sender_id()
        if not guild_id: return

        # 处理烧砖进度
        if guild_id in self.burning_status:
            for burner_id, status in list(self.burning_status[guild_id].items()):
                if burner_id != user_id: # 群友发消息增加进度
                    status["count"] += 1
                    if status["count"] >= status["target"]:
                        user_info = self._get_user(guild_id, burner_id)
                        user_info["brick"] += 1
                        self._save_data()
                        del self.burning_status[guild_id][burner_id]
                        await self.context.send_message(event.unified_msg_origin, MessageChain().at(burner_id).text(" 砖已经烧好啦！"))

        # 处理搬砖进度
        if guild_id in self.working_status:
            for worker_id, status in list(self.working_status[guild_id].items()):
                if worker_id != user_id:
                    status["count"] += 1
                    if status["count"] >= status["target"]:
                        # 搬砖成功逻辑
                        user_info = self._get_user(guild_id, worker_id)
                        gain_range = self.config.get("work_range", "1,2").split(",")
                        gain = random.randint(int(gain_range[0]), int(gain_range[1]))
                        user_info["brick"] = min(user_info["brick"] + gain, self.config.get("max_brick", 10))
                        self._save_data()
                        del self.working_status[guild_id][worker_id]
                        await self.context.send_message(event.unified_msg_origin, MessageChain().at(worker_id).text(f" 搬砖完成！获得了 {gain} 块砖头。"))

    @filter.command("砖头帮助")
    async def help(self, event: AstrMessageEvent):
        help_text = (
            "🧱 砖头插件指令帮助 🧱\n"
            "--------------------\n"
            "【查看砖头】: 查看你拥有的砖头数量\n"
            "【烧砖】: 开始烧制砖头（需群友发消息）\n"
            "【拍人 @用户】: 使用砖头拍晕对方\n"
            "【随机拍人】: 随机拍晕一个幸运儿\n"
            "【偷砖 @用户】: 尝试偷取对方的砖头\n"
            "【搬砖】: 开始搬砖，群友发言后获得砖头\n"
            "【砖头签到】: 每日领取砖头\n"
            "【别拍我了】: 将自己加入黑名单（不可逆）\n"
            "--------------------\n"
            "管理员指令:\n"
            "【禁砖头】: (仅群主/管理) 禁用本群砖头功能\n"
            "【开启砖头】: (仅群主/管理) 开启本群砖头功能\n"
            "【修改配置 项 值】: 修改插件配置"
        )
        yield event.plain_result(help_text)

    @filter.command("查看砖头", alias={"砖头.查看"})
    async def view_brick(self, event: AstrMessageEvent):
        guild_id = event.get_group_id()
        user_id = event.get_sender_id()
        if not guild_id: yield event.plain_result("请在群聊中使用此指令。"); return
        user_info = self._get_user(guild_id, user_id)
        yield event.plain_result(f"你有 {user_info['brick']}/{self.config.get('max_brick', 10)} 块砖头")

    @filter.command("烧砖", alias={"砖头.烧砖"})
    async def burn_brick(self, event: AstrMessageEvent):
        guild_id = event.get_group_id()
        user_id = event.get_sender_id()
        if not guild_id: yield event.plain_result("请在群聊中使用此指令。"); return
        
        user_info = self._get_user(guild_id, user_id)
        max_brick = self.config.get("max_brick", 10)
        if user_info["brick"] >= max_brick:
            yield event.plain_result(f"你最多只能拥有 {max_brick} 块砖")
            return

        if guild_id not in self.burning_status: self.burning_status[guild_id] = {}
        if user_id in self.burning_status[guild_id]:
            yield event.plain_result("已经在烧砖了")
            return

        cost = self.config.get("burn_cost", 20)
        self.burning_status[guild_id][user_id] = {"count": 0, "target": cost}
        yield event.plain_result(f"现在开始烧砖啦，群友每发送 {cost} 条消息就烧好一块砖")

    async def _mute_user(self, event: AstrMessageEvent, user_id: str, duration: int):
        # 这里需要适配不同平台的禁言逻辑，AstrBot 核心提供了统一接口吗？
        # 参考文档，可以使用 call_action 或者如果平台支持。
        # 这里简化处理，先打印日志，实际使用中需要根据平台调用。
        try:
            # 尝试调用通用的禁言逻辑（如果适配器支持）
            # 在 OneBot V11 中：
            if event.get_platform_name() == "aiocqhttp":
                from astrbot.core.platform.sources.aiocqhttp.aiocqhttp_message_event import AiocqhttpMessageEvent
                if isinstance(event, AiocqhttpMessageEvent):
                    client = event.bot
                    await client.api.call_action('set_group_mute', group_id=event.get_group_id(), user_id=user_id, duration=duration)
        except Exception as e:
            print(f"Mute failed: {e}")

    @filter.command("拍人", alias={"砖头.拍人"})
    async def slap(self, event: AstrMessageEvent):
        guild_id = event.get_group_id()
        user_id = event.get_sender_id()
        if not guild_id: yield event.plain_result("请在群聊中使用此指令。"); return

        # 获取 @ 的人
        target_id = None
        for component in event.message_obj.message:
            if isinstance(component, Comp.At):
                target_id = str(component.qq)
                break
        
        if not target_id:
            yield event.plain_result("请 @ 一个你想拍的人")
            return
        
        user_info = self._get_user(guild_id, user_id)
        if user_info["brick"] <= 0:
            yield event.plain_result("你在这个群还没有砖头，先去烧点吧")
            return

        now = time.time()
        cooldown = self.config.get("slap_cooldown", 60)
        if now - user_info["last_slap"] < cooldown:
            yield event.plain_result(f"{int(cooldown - (now - user_info['last_slap']))} 秒后才能再拍人哦")
            return

        user_info["brick"] -= 1
        user_info["last_slap"] = now
        self._save_data()

        prob = self.config.get("reverse_prob", 10) / 100
        mute_time = random.randint(self.config.get("min_mute_time", 10), self.config.get("max_mute_time", 120))

        if random.random() < prob:
            # 反杀
            await self._mute_user(event, user_id, mute_time)
            yield event.chain_result([Comp.At(qq=target_id), Comp.Plain(f" 夺过你的砖头，把你拍晕了 {mute_time} 秒")])
        else:
            # 成功
            await self._mute_user(event, target_id, mute_time)
            yield event.chain_result([Comp.At(qq=target_id), Comp.Plain(f" 你被 "), Comp.At(qq=user_id), Comp.Plain(f" 拍晕了 {mute_time} 秒")])

    @filter.command("随机拍人", alias={"砖头.随机拍人"})
    async def random_slap(self, event: AstrMessageEvent):
        # 简化版：由于获取群成员列表较为复杂且依赖平台，这里仅处理简单的逻辑
        # 如果需要完整功能，需要调用平台 API 获取成员列表
        yield event.plain_result("随机拍人功能需要平台支持获取成员列表，请直接使用 拍人 @用户")

    @filter.command("偷砖", alias={"砖头.偷砖"})
    async def steal_brick(self, event: AstrMessageEvent):
        if not self.config.get("enable_steal"): yield event.plain_result("偷砖功能未开启。"); return
        guild_id = event.get_group_id()
        user_id = event.get_sender_id()
        if not guild_id: yield event.plain_result("请在群聊中使用此指令。"); return

        now = time.time()
        last_time = self.last_steal_time.get(user_id, 0)
        cooldown = self.config.get("steal_cooldown", 300)
        if now - last_time < cooldown:
            yield event.plain_result(f"偷砖冷却中，还剩 {int(cooldown - (now - last_time))} 秒")
            return

        target_id = None
        for component in event.message_obj.message:
            if isinstance(component, Comp.At):
                target_id = str(component.qq)
                break
        
        if not target_id or target_id == user_id:
            yield event.plain_result("请 @ 一个你想偷的目标")
            return

        self.last_steal_time[user_id] = now
        fail_prob = self.config.get("steal_fail_prob", 30) / 100

        if random.random() < fail_prob:
            # 失败被禁言
            mute_time = self.config.get("steal_mute_time", 60)
            await self._mute_user(event, user_id, mute_time)
            yield event.plain_result(f"偷砖失败！你被巡逻队抓住了，禁言 {mute_time} 秒")
        else:
            # 成功
            target_info = self._get_user(guild_id, target_id)
            if target_info["brick"] <= 0:
                yield event.plain_result("对方兜里空空如也，啥也没偷到")
                return
            
            s_range = self.config.get("steal_range", "1,3").split(",")
            steal_num = random.randint(int(s_range[0]), int(s_range[1]))
            actual_steal = min(steal_num, target_info["brick"])
            
            user_info = self._get_user(guild_id, user_id)
            user_info["brick"] = min(user_info["brick"] + actual_steal, self.config.get("max_brick", 10))
            target_info["brick"] -= actual_steal
            self._save_data()
            yield event.plain_result(f"成功偷到了 {actual_steal} 块砖头！")

    @filter.command("搬砖", alias={"砖头.搬砖"})
    async def work_brick(self, event: AstrMessageEvent):
        if not self.config.get("enable_work"): yield event.plain_result("搬砖功能未开启。"); return
        guild_id = event.get_group_id()
        user_id = event.get_sender_id()
        if not guild_id: yield event.plain_result("请在群聊中使用此指令。"); return

        if random.random() < (self.config.get("work_fail_prob", 10) / 100):
            mute_time = 60 # 累晕禁言1分钟
            await self._mute_user(event, user_id, mute_time)
            yield event.plain_result(f"你搬砖太累直接晕倒了，禁言 {mute_time} 秒")
            return

        if guild_id not in self.working_status: self.working_status[guild_id] = {}
        if user_id in self.working_status[guild_id]:
            yield event.plain_result("已经在搬砖了")
            return

        target = self.config.get("work_message_count", 10)
        self.working_status[guild_id][user_id] = {"count": 0, "target": target}
        yield event.plain_result(f"开始搬砖！等群友再说 {target} 句话就能拿到砖头了。")

    @filter.command("砖头签到", alias={"砖头.签到"})
    async def daily_check(self, event: AstrMessageEvent):
        if not self.config.get("enable_daily"): yield event.plain_result("签到功能未开启。"); return
        guild_id = event.get_group_id()
        user_id = event.get_sender_id()
        if not guild_id: yield event.plain_result("请在群聊中使用此指令。"); return

        user_info = self._get_user(guild_id, user_id)
        today = time.strftime("%Y-%m-%d")

        if user_info["last_check"] == today:
            yield event.plain_result("今天已经签到过了哦")
            return

        gain = 0
        if user_info.get("is_new", False):
            gain = self.config.get("first_use_gain", 5)
            user_info["is_new"] = False
            msg = f"新用户首次签到！获得了 {gain} 块砖头。"
        else:
            g_range = self.config.get("daily_gain", "1,5").split(",")
            gain = random.randint(int(g_range[0]), int(g_range[1]))
            msg = f"签到成功，获得了 {gain} 块砖头。"

        user_info["brick"] = min(user_info["brick"] + gain, self.config.get("max_brick", 10))
        user_info["last_check"] = today
        self._save_data()
        yield event.plain_result(f"{msg} 当前拥有 {user_info['brick']} 块。")

    @filter.command("别拍我了")
    async def self_blacklist(self, event: AstrMessageEvent):
        if not self.config.get("enable_user_blacklist"): return
        user_id = event.get_sender_id()
        if user_id in self.blacklist_confirm:
            self.user_data["user_blacklist"].append(user_id)
            self._save_data()
            self.blacklist_confirm.remove(user_id)
            yield event.plain_result("已将你拉入黑名单，我再也不会理你了。")
        else:
            self.blacklist_confirm.add(user_id)
            yield event.plain_result("开启黑名单后无法自主取消，如真需开启请再次输入 “别拍我了”。")

    @filter.permission_type(filter.PermissionType.ADMIN)
    @filter.command("禁砖头")
    async def ban_group(self, event: AstrMessageEvent):
        if not self.config.get("enable_group_blacklist"): return
        group_id = event.get_group_id()
        if not group_id: return
        if group_id not in self.user_data["group_blacklist"]:
            self.user_data["group_blacklist"].append(group_id)
            self._save_data()
            yield event.plain_result("本群已进入砖头黑名单。")

    @filter.permission_type(filter.PermissionType.ADMIN)
    @filter.command("开启砖头")
    async def unban_group(self, event: AstrMessageEvent):
        if not self.config.get("enable_group_blacklist"): return
        group_id = event.get_group_id()
        if not group_id: return
        if group_id in self.user_data["group_blacklist"]:
            self.user_data["group_blacklist"].remove(group_id)
            self._save_data()
            yield event.plain_result("本群砖头功能已恢复。")

    @filter.permission_type(filter.PermissionType.ADMIN)
    @filter.command("修改配置")
    async def change_config(self, event: AstrMessageEvent, key: str, value: str):
        # 简单的配置修改逻辑
        if key in self.config:
            # 尝试转换类型
            old_val = self.config[key]
            try:
                if isinstance(old_val, bool):
                    new_val = value.lower() in ["true", "1", "是", "开启"]
                elif isinstance(old_val, int):
                    new_val = int(value)
                elif isinstance(old_val, list):
                    new_val = value.split(",")
                else:
                    new_val = value
                
                self.config[key] = new_val
                self.config.save_config()
                yield event.plain_result(f"配置项 {key} 已修改为 {new_val}")
            except Exception as e:
                yield event.plain_result(f"修改失败：{e}")
        else:
            yield event.plain_result(f"不存在配置项：{key}")
