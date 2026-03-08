import random
import time
import asyncio
from typing import Dict, List, Any
from astrbot.api.event import filter, AstrMessageEvent, MessageEventResult
from astrbot.api.star import Context, Star, register
from astrbot.api import logger
from astrbot.api.message_components import Plain, At

@register("brick", "AstrBot-Developer", "烧制砖块，然后拍晕群友！支持偷砖、搬砖、签到及黑名单功能。", "1.0.0")
class BrickPlugin(Star):
    def __init__(self, context: Context, config: dict = None):
        super().__init__(context)
        self.config = config if config else {}
        # 内存存储状态
        self.brick_data = {}
        self.burning_status = {}
        self.user_states = {}
        self.work_status = {}

    def get_user_data(self, guild_id: str, user_id: str):
        if guild_id not in self.brick_data:
            self.brick_data[guild_id] = {}
        if user_id not in self.brick_data[guild_id]:
            self.brick_data[guild_id][user_id] = {"brick": 0, "last_slap": 0, "checkin_day": ""}
        return self.brick_data[guild_id][user_id]

    def get_user_state(self, guild_id: str, user_id: str):
        if guild_id not in self.user_states:
            self.user_states[guild_id] = {}
        if user_id not in self.user_states[guild_id]:
            self.user_states[guild_id][user_id] = {"muted_until": 0, "last_steal": 0, "blacklist_confirm": False}
        return self.user_states[guild_id][user_id]

    def is_muted(self, guild_id: str, user_id: str):
        state = self.get_user_state(guild_id, user_id)
        return time.time() < state["muted_until"]

    def is_blacklisted(self, guild_id: str, user_id: str):
        if self.config.get("enable_guild_blacklist", True):
            if guild_id in self.config.get("guild_blacklist", []):
                return True
        if self.config.get("enable_user_blacklist", True):
            if user_id in self.config.get("user_blacklist", []):
                return True
        return False

    @filter.event_message_type(filter.EventMessageType.GROUP_MESSAGE)
    async def handle_burning_and_working(self, event: AstrMessageEvent):
        guild_id = event.message_obj.group_id
        user_id = event.get_sender_id()
        
        if self.is_blacklisted(guild_id, user_id):
            return

        # 检查是否禁言中
        if self.is_muted(guild_id, user_id):
            event.stop_event()
            return

        # 处理烧砖进度
        if guild_id in self.burning_status:
            for burner_id, status in list(self.burning_status[guild_id].items()):
                if burner_id != user_id:
                    status["message_count"] += 1
                    if status["message_count"] >= status["target"]:
                        data = self.get_user_data(guild_id, burner_id)
                        data["brick"] = min(data["brick"] + 1, self.config.get("max_brick", 10))
                        await self.context.send_message(guild_id, [At(qq=burner_id), Plain(" 砖已经烧好啦！")])
                        del self.burning_status[guild_id][burner_id]

        # 处理搬砖进度
        if guild_id in self.work_status:
            for worker_id, status in list(self.work_status[guild_id].items()):
                if worker_id != user_id:
                    status["message_count"] += 1
                    if status["message_count"] >= status["target"]:
                        data = self.get_user_data(guild_id, worker_id)
                        if random.randint(1, 100) <= self.config.get("work_fail_prob", 10):
                            mute_time = self.config.get("max_mute_time", 120)
                            state = self.get_user_state(guild_id, worker_id)
                            state["muted_until"] = time.time() + mute_time
                            await self.context.send_message(guild_id, [At(qq=worker_id), Plain(f" 搬砖太累晕倒了，禁言 {mute_time} 秒！")])
                        else:
                            r_range = self.config.get("work_range", "1,5")
                            try:
                                r_min, r_max = map(int, r_range.split(","))
                            except:
                                r_min, r_max = 1, 5
                            gain = random.randint(r_min, r_max)
                            data["brick"] = min(data["brick"] + gain, self.config.get("max_brick", 10))
                            await self.context.send_message(guild_id, [At(qq=worker_id), Plain(f" 搬砖完成，获得了 {gain} 块砖头！")])
                        del self.work_status[guild_id][worker_id]

    @filter.command("砖头")
    async def brick_help(self, event: AstrMessageEvent):
        """显示砖头帮助"""
        help_text = """【砖头插件帮助】
/烧砖 - 开始烧制砖块
/拍人 @用户 - 使用砖头拍晕对方
/随机拍人 - 随机拍晕一个群友
/查看砖头 - 查看自己的砖头数量
/砖头签到 - 每日签到领砖头
/偷砖 @用户 - 偷取对方的砖头
/搬砖 - 开启搬砖任务
/别拍我了 - 开启个人黑名单
/禁砖头 - (管理员) 禁用本群砖头
/开启砖头 - (管理员) 开启本群砖头
/砖头配置 [项] [值] - (管理员) 修改配置"""
        yield event.plain_result(help_text)

    @filter.command("烧砖", alias={"砖头.烧砖"})
    async def burn_brick(self, event: AstrMessageEvent):
        """开始烧砖"""
        guild_id = event.message_obj.group_id
        user_id = event.get_sender_id()
        if self.is_blacklisted(guild_id, user_id): return
        
        data = self.get_user_data(guild_id, user_id)
        if data["brick"] >= self.config.get("max_brick", 10):
            yield event.plain_result(f"你最多只能拥有{self.config.get('max_brick', 10)}块砖")
            return

        if guild_id not in self.burning_status: self.burning_status[guild_id] = {}
        if user_id in self.burning_status[guild_id]:
            yield event.plain_result("已经在烧砖了")
            return

        cost = self.config.get("cost", 10)
        self.burning_status[guild_id][user_id] = {"message_count": 0, "target": cost}
        yield event.plain_result(f"现在开始烧砖啦，群友每发送{cost}条消息就烧好一块砖")

    @filter.command("拍人", alias={"砖头.拍人"})
    async def slap_user(self, event: AstrMessageEvent):
        """拍晕对方"""
        guild_id = event.message_obj.group_id
        user_id = event.get_sender_id()
        if self.is_blacklisted(guild_id, user_id): return

        target_id = ""
        for comp in event.get_messages():
            if isinstance(comp, At):
                target_id = str(comp.qq)
                break
        
        if not target_id:
            yield event.plain_result("请 @ 一个你要拍的人")
            return

        data = self.get_user_data(guild_id, user_id)
        if data["brick"] <= 0:
            yield event.plain_result("你在这个群还没有砖头，使用 /烧砖 烧点砖头吧")
            return

        cooldown = self.config.get("cooldown", 60)
        if time.time() - data["last_slap"] < cooldown:
            yield event.plain_result(f"{int(cooldown - (time.time() - data['last_slap']))} 秒后才能再拍人哦")
            return

        if self.is_muted(guild_id, target_id):
            yield event.plain_result("他已经晕了...")
            return

        data["brick"] -= 1
        data["last_slap"] = time.time()

        mute_time = random.randint(self.config.get("min_mute_time", 10), self.config.get("max_mute_time", 120))
        
        prob = self.config.get("reverse_prob", 10)
        if random.randint(1, 100) <= prob:
            state = self.get_user_state(guild_id, user_id)
            state["muted_until"] = time.time() + mute_time
            yield event.chain_result([At(qq=target_id), Plain(f" 夺过你的砖头，把你拍晕了 {mute_time} 秒")])
        else:
            state = self.get_user_state(guild_id, target_id)
            state["muted_until"] = time.time() + mute_time
            yield event.chain_result([At(qq=target_id), Plain(f" 你被 "), At(qq=user_id), Plain(f" 拍晕了 {mute_time} 秒")])

    @filter.command("随机拍人", alias={"砖头.随机拍人"})
    async def random_slap(self, event: AstrMessageEvent):
        """随机拍人"""
        guild_id = event.message_obj.group_id
        if guild_id not in self.brick_data or not self.brick_data[guild_id]:
            yield event.plain_result("群里还没有人拥有砖头，无法随机拍人")
            return
        
        target_id = random.choice(list(self.brick_data[guild_id].keys()))
        event.message_obj.message = [Plain("/拍人 "), At(qq=target_id)]
        async for res in self.slap_user(event):
            yield res

    @filter.command("查看砖头", alias={"砖头.查看"})
    async def view_brick(self, event: AstrMessageEvent):
        """查看砖头"""
        guild_id = event.message_obj.group_id
        user_id = event.get_sender_id()
        data = self.get_user_data(guild_id, user_id)
        yield event.plain_result(f"你有 {data['brick']}/{self.config.get('max_brick', 10)} 块砖头")

    @filter.command("砖头签到", alias={"砖头.签到"})
    async def checkin(self, event: AstrMessageEvent):
        """签到领砖"""
        if not self.config.get("enable_checkin", True): return
        guild_id = event.message_obj.group_id
        user_id = event.get_sender_id()
        if self.is_blacklisted(guild_id, user_id): return

        data = self.get_user_data(guild_id, user_id)
        today = time.strftime("%Y-%m-%d")
        
        if data["checkin_day"] == today:
            yield event.plain_result("你今天已经签到过了")
            return

        gain = self.config.get("checkin_gain", 5)
        data["brick"] = min(data["brick"] + gain, self.config.get("max_brick", 10))
        data["checkin_day"] = today
        yield event.plain_result(f"签到成功，你获得了 {gain} 块砖头，现在有 {data['brick']}/{self.config.get('max_brick', 10)} 块砖头")

    @filter.command("偷砖")
    async def steal_brick(self, event: AstrMessageEvent):
        """偷取砖头"""
        if not self.config.get("enable_steal", True): return
        guild_id = event.message_obj.group_id
        user_id = event.get_sender_id()
        if self.is_blacklisted(guild_id, user_id): return

        target_id = ""
        for comp in event.get_messages():
            if isinstance(comp, At):
                target_id = str(comp.qq)
                break
        
        if not target_id:
            yield event.plain_result("请 @ 一个你要偷的人")
            return

        state = self.get_user_state(guild_id, user_id)
        cooldown = self.config.get("steal_cooldown", 300)
        if time.time() - state["last_steal"] < cooldown:
            yield event.plain_result(f"{int(cooldown - (time.time() - state['last_steal']))} 秒后才能再偷砖哦")
            return

        state["last_steal"] = time.time()
        
        if random.randint(1, 100) <= self.config.get("steal_fail_prob", 50):
            mute_time = self.config.get("steal_fail_mute", 60)
            state["muted_until"] = time.time() + mute_time
            yield event.plain_result(f"偷砖失败，被发现并禁言 {mute_time} 秒！")
        else:
            target_data = self.get_user_data(guild_id, target_id)
            if target_data["brick"] <= 0:
                yield event.plain_result("对方一块砖都没有，白忙活了...")
                return
            
            s_range = self.config.get("steal_range", "1,3")
            try:
                r_min, r_max = map(int, s_range.split(","))
            except:
                r_min, r_max = 1, 3
            steal_count = min(random.randint(r_min, r_max), target_data["brick"])
            
            target_data["brick"] -= steal_count
            my_data = self.get_user_data(guild_id, user_id)
            my_data["brick"] = min(my_data["brick"] + steal_count, self.config.get("max_brick", 10))
            
            yield event.plain_result(f"偷砖成功！从对方那里顺走了 {steal_count} 块砖头！")

    @filter.command("搬砖")
    async def work_brick(self, event: AstrMessageEvent):
        """开启搬砖"""
        if not self.config.get("enable_work", True): return
        guild_id = event.message_obj.group_id
        user_id = event.get_sender_id()
        if self.is_blacklisted(guild_id, user_id): return

        if guild_id not in self.work_status: self.work_status[guild_id] = {}
        if user_id in self.work_status[guild_id]:
            yield event.plain_result("已经在搬砖了")
            return

        count = self.config.get("work_msg_count", 5)
        self.work_status[guild_id][user_id] = {"message_count": 0, "target": count}
        yield event.plain_result(f"开始搬砖！群友发送 {count} 条消息后即可获得砖头。")

    @filter.command("别拍我了")
    async def user_blacklist_cmd(self, event: AstrMessageEvent):
        """个人黑名单"""
        if not self.config.get("enable_user_blacklist", True): return
        guild_id = event.message_obj.group_id
        user_id = event.get_sender_id()
        state = self.get_user_state(guild_id, user_id)

        if not state["blacklist_confirm"]:
            state["blacklist_confirm"] = True
            yield event.plain_result("开启黑名单后无法自主取消，如真需开启请再次输入 “别拍我了”。")
        else:
            blacklist = self.config.get("user_blacklist", [])
            if user_id not in blacklist:
                blacklist.append(user_id)
                self.config["user_blacklist"] = blacklist
                self.context.save_config()
            yield event.plain_result("已将你拉入黑名单，以后我不会再理你了。")

    @filter.command("禁砖头")
    async def guild_blacklist_cmd(self, event: AstrMessageEvent):
        """禁用群砖头 (管理员)"""
        if not self.config.get("enable_guild_blacklist", True): return
        if not event.message_obj.sender.role == "admin" and not event.message_obj.sender.role == "owner":
             if not await self.context.is_admin(event.get_sender_id()):
                 return

        guild_id = event.message_obj.group_id
        blacklist = self.config.get("guild_blacklist", [])
        if guild_id not in blacklist:
            blacklist.append(guild_id)
            self.config["guild_blacklist"] = blacklist
            self.context.save_config()
        yield event.plain_result("本群砖头已禁用。")

    @filter.command("开启砖头")
    async def guild_unblacklist_cmd(self, event: AstrMessageEvent):
        """开启群砖头 (管理员)"""
        if not self.config.get("enable_guild_blacklist", True): return
        if not event.message_obj.sender.role == "admin" and not event.message_obj.sender.role == "owner":
             if not await self.context.is_admin(event.get_sender_id()):
                 return

        guild_id = event.message_obj.group_id
        blacklist = self.config.get("guild_blacklist", [])
        if guild_id in blacklist:
            blacklist.remove(guild_id)
            self.config["guild_blacklist"] = blacklist
            self.context.save_config()
        yield event.plain_result("本群砖头已开启。")

    @filter.permission_type(filter.PermissionType.ADMIN)
    @filter.command("砖头配置")
    async def set_config(self, event: AstrMessageEvent, key: str = None, value: str = None):
        """修改配置 (管理员)"""
        if not key:
            yield event.plain_result(f"当前配置项: {', '.join(self.config.keys())}")
            return
        
        if key not in self.config:
            yield event.plain_result(f"未找到配置项: {key}")
            return
        
        if value is None:
            yield event.plain_result(f"{key} 的当前值为: {self.config[key]}")
            return

        old_val = self.config[key]
        try:
            if isinstance(old_val, bool):
                new_val = value.lower() in ["true", "1", "yes", "开启"]
            elif isinstance(old_val, int):
                new_val = int(value)
            elif isinstance(old_val, list):
                new_val = value.split(",")
            else:
                new_val = value
            
            self.config[key] = new_val
            self.context.save_config()
            yield event.plain_result(f"配置 {key} 已修改为: {new_val}")
        except Exception as e:
            yield event.plain_result(f"修改失败: {str(e)}")
