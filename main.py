import random
from datetime import datetime
from aiocqhttp import CQHttp
import aiocqhttp
from astrbot.api.event import filter
from astrbot.api.star import Context, Star, register
from astrbot.core.config.astrbot_config import AstrBotConfig
import astrbot.api.message_components as Comp
from astrbot.core.platform.sources.aiocqhttp.aiocqhttp_message_event import (
    AiocqhttpMessageEvent,
)
from astrbot.core.star.filter.permission import PermissionType

# 点赞成功回复
success_responses = [
    "👍{total_likes}",
    "赞了赞了",
    "点赞成功！",
    "给{username}点了{total_likes}个赞",
    "赞送出去啦！一共{total_likes}个哦！",
    "为{username}点赞成功！总共{total_likes}个！",
    "点了{total_likes}个，快查收吧！",
    "赞已送达，请注意查收~ 一共{total_likes}个！",
    "给{username}点了{total_likes}个赞，记得回赞哟！",
    "赞了{total_likes}次，看看收到没？",
    "点了{total_likes}赞，没收到可能是我被风控了",
]

# 点赞数到达上限回复
limit_responses = [
    "今天给{username}的赞已达上限",
    "赞了那么多还不够吗？",
    "{username}别太贪心哟~",
    "今天赞过啦！",
    "今天已经赞过啦~",
    "已经赞过啦~",
    "还想要赞？不给了！",
    "已经赞过啦，别再点啦！",
]

# 陌生人点赞回复
stranger_responses = [
    "不加好友不赞",
    "我和你有那么熟吗？",
    "你谁呀？",
    "你是我什么人凭啥要我赞你？",
    "不想赞你这个陌生人",
    "我不认识你，不赞！",
    "加我好友了吗就想要我赞你？",
    "滚！",
]


@register(
    "astrbot_plugin_zanwo_shell",
    "Shell",
    "发送 赞我 自动点赞",
    "1.0.2",
    "https://github.com/1592363624/astrbot_plugin_zanwo_shell",
)
class zanwo(Star):
    def __init__(self, context: Context, config: AstrBotConfig):
        super().__init__(context)
        self.config = config
        self.success_responses: list[str] = success_responses

        # 群聊白名单
        self.enable_white_list_groups: bool = config.get(
            "enable_white_list_groups", False
        )
        self.white_list_groups: list[str] = config.get("white_list_groups", [])
        # 订阅点赞的用户ID列表
        self.subscribed_users: list[str] = config.get("subscribed_users", [])
        # 点赞日期
        self.zanwo_date: str = config.get("zanwo_date", None)
        # 订阅点赞审批管理员ID列表（插件配置）
        raw_subscribe_admins = config.get("subscribe_admins", [])
        if isinstance(raw_subscribe_admins, str):
            parts = (
                raw_subscribe_admins.replace("，", ",")
                .split(",")
            )
            self.subscribe_admins: list[str] = [
                p.strip() for p in parts if p.strip()
            ]
        elif isinstance(raw_subscribe_admins, list):
            self.subscribe_admins: list[str] = [
                str(p).strip() for p in raw_subscribe_admins if str(p).strip()
            ]
        else:
            self.subscribe_admins: list[str] = []
        # 待审批的订阅请求，key 为 "group_id:sender_id"
        self.pending_subscriptions: dict[str, dict] = {}

    async def _like(self, client: CQHttp, ids: list[str]) -> str:
        """
        点赞的核心逻辑
        :param client: CQHttp客户端
        :param ids: 用户ID列表
        """
        replys = []
        for id in ids:
            total_likes = 0
            username = (await client.get_stranger_info(user_id=int(id))).get(
                "nickname", "未知用户"
            )
            for _ in range(5):
                try:
                    await client.send_like(user_id=int(id), times=10)  # 点赞10次
                    total_likes += 10
                except aiocqhttp.exceptions.ActionFailed as e:
                    error_message = str(e)
                    if "已达" in error_message:
                        error_reply = random.choice(limit_responses)
                    elif "权限" in error_message:
                        error_reply = "你设了权限不许陌生人赞你"
                    else:
                        error_reply = random.choice(stranger_responses)
                    break

            reply = random.choice(self.success_responses) if total_likes > 0 else error_reply

             # 检查 reply 中是否包含占位符，并根据需要进行替换
            if "{username}" in reply:
                reply = reply.replace("{username}", username)
            if "{total_likes}" in reply:
                reply = reply.replace("{total_likes}", str(total_likes))

            replys.append(reply)

        return "\n".join(replys).strip()

    @staticmethod
    def get_ats(event: AiocqhttpMessageEvent) -> list[str]:
        """获取被at者们的id列表"""
        messages = event.get_messages()
        self_id = event.get_self_id()
        return [
            str(seg.qq)
            for seg in messages
            if (isinstance(seg, Comp.At) and str(seg.qq) != self_id)
        ]

    @filter.regex(r"^赞.*")
    async def like_me(self, event: AiocqhttpMessageEvent):
        """给用户点赞"""
        # 检查群组id是否在白名单中, 若没填写白名单则不检查
        if self.enable_white_list_groups:
            if event.get_group_id() not in self.white_list_groups:
                return
        target_ids = []
        if event.message_str == "赞我":
            target_ids.append(event.get_sender_id())
        if not target_ids:
            target_ids = self.get_ats(event)
        if not target_ids:
            return
        client = event.bot
        result = await self._like(client, target_ids)
        yield event.plain_result(result)

        # 触发自动点赞
        if self.subscribed_users and self.zanwo_date != datetime.now().date().strftime(
            "%Y-%m-%d"
        ):
            await self._like(client, self.subscribed_users)
            self.zanwo_date = datetime.now().date().strftime("%Y-%m-%d")
            self.config.save_config()

    @filter.command("订阅点赞")
    async def subscribe_like(self, event: AiocqhttpMessageEvent):
        """订阅点赞"""
        sender_id = event.get_sender_id()
        group_id = event.get_group_id()
        key = f"{group_id}:{sender_id}"
        if sender_id in self.subscribed_users:
            yield event.plain_result("你已经订阅点赞了哦~")
            return
        if not self.subscribe_admins:
            yield event.plain_result("当前未配置订阅审核管理员，请联系bot管理员配置后再试~")
            return
        if key in self.pending_subscriptions:
            yield event.plain_result("你已经提交过订阅申请啦，请等待管理员审批~")
            return
        self.pending_subscriptions[key] = {
            "group_id": group_id,
            "user_id": sender_id,
        }
        client = event.bot
        try:
            user_info = await client.get_stranger_info(user_id=int(sender_id))
            nickname = user_info.get("nickname", "未知用户")
        except Exception:
            nickname = "未知用户"
        any_success = False
        for admin_id in self.subscribe_admins:
            try:
                await client.send_private_msg(
                    user_id=int(admin_id),
                    message=(
                        "[订阅点赞申请]\n"
                        f"群号: {group_id}\n"
                        f"申请人: {nickname}（QQ: {sender_id}）\n"
                        "请在私聊中回复以下指令之一（可引用本消息）：\n"
                        f"/同意订阅点赞 {group_id} {sender_id}\n"
                        f"/拒绝订阅点赞 {group_id} {sender_id}"
                    ),
                )
                any_success = True
            except Exception:
                continue
        if any_success:
            yield event.plain_result(
                "已向插件管理员提交订阅申请，请等待管理员在私聊中审批结果。"
            )
        else:
            yield event.plain_result(
                "已记录你的订阅申请，但向插件管理员发送私聊失败。\n"
                "请确认插件管理员已与bot互为好友并允许私聊，"
                "管理员也可主动私聊bot发送 /同意订阅点赞 群号 用户QQ 进行审批。"
            )

    @filter.command("同意订阅点赞")
    async def approve_subscribe_like(self, event: AiocqhttpMessageEvent):
        """同意订阅点赞申请（插件管理员，私聊）"""
        admin_id = event.get_sender_id()
        if admin_id not in self.subscribe_admins:
            yield event.plain_result("你不是本插件配置的管理员，无法审批订阅请求~")
            return
        parts = event.message_str.strip().split()
        if len(parts) < 3:
            yield event.plain_result("用法：/同意订阅点赞 群号 用户QQ")
            return
        group_id = parts[1]
        user_id = parts[2]
        replies = []
        key = f"{group_id}:{user_id}"
        if key not in self.pending_subscriptions:
            if user_id in self.subscribed_users:
                replies.append(f"{user_id} 已经是订阅用户啦，无需再次同意~")
            else:
                replies.append(f"未找到 {user_id} 在群 {group_id} 的订阅申请，无法同意哦~")
        else:
            if user_id not in self.subscribed_users:
                self.subscribed_users.append(user_id)
                self.config.save_config()
            self.pending_subscriptions.pop(key, None)
            replies.append(f"已同意群 {group_id} 中 {user_id} 的订阅点赞申请，将为其每天自动点赞~")
            client = event.bot
            try:
                await client.send_group_msg(
                    group_id=int(group_id),
                    message=f"{user_id} 的订阅点赞申请已通过，将为TA每天自动点赞~",
                )
            except Exception:
                pass
        if replies:
            yield event.plain_result("\n".join(replies))

    @filter.command("拒绝订阅点赞")
    async def reject_subscribe_like(self, event: AiocqhttpMessageEvent):
        """拒绝订阅点赞申请（插件管理员，私聊）"""
        admin_id = event.get_sender_id()
        if admin_id not in self.subscribe_admins:
            yield event.plain_result("你不是本插件配置的管理员，无法审批订阅请求~")
            return
        parts = event.message_str.strip().split()
        if len(parts) < 3:
            yield event.plain_result("用法：/拒绝订阅点赞 群号 用户QQ")
            return
        group_id = parts[1]
        user_id = parts[2]
        replies = []
        key = f"{group_id}:{user_id}"
        if key not in self.pending_subscriptions:
            replies.append(f"未找到 {user_id} 在群 {group_id} 的订阅申请，无法拒绝哦~")
        else:
            self.pending_subscriptions.pop(key, None)
            replies.append(f"已拒绝群 {group_id} 中 {user_id} 的订阅点赞申请。")
            client = event.bot
            try:
                await client.send_group_msg(
                    group_id=int(group_id),
                    message=f"{user_id} 的订阅点赞申请已被管理员拒绝。",
                )
            except Exception:
                pass
        if replies:
            yield event.plain_result("\n".join(replies))

    @filter.command("取消订阅点赞")
    async def unsubscribe_like(self, event: AiocqhttpMessageEvent):
        """取消订阅点赞"""
        sender_id = event.get_sender_id()
        if sender_id not in self.subscribed_users:
            yield event.plain_result("你还没有订阅点赞哦~")
            return
        self.subscribed_users.remove(sender_id)
        self.config.save_config()
        yield event.plain_result("已取消订阅！我将不再自动给你点赞")

    @filter.command("订阅点赞列表")
    async def like_list(self, event: AiocqhttpMessageEvent):
        """查看订阅点赞的用户ID列表"""

        if not self.subscribed_users:
            yield event.plain_result("当前没有订阅点赞的用户哦~")
            return
        users_str = "\n".join(self.subscribed_users).strip()
        yield event.plain_result(f"当前订阅点赞的用户ID列表：\n{users_str}")

    @filter.permission_type(PermissionType.ADMIN)
    @filter.command("谁赞了bot", alias={"谁赞了你"})
    async def get_profile_like(self, event: AiocqhttpMessageEvent):
        """获取bot自身点赞列表"""
        client = event.bot
        data = await client.get_profile_like()
        reply = ""
        user_infos = data.get("favoriteInfo", {}).get("userInfos", [])
        for user in user_infos:
            if (
                "nick" in user
                and user["nick"]
                and "count" in user
                and user["count"] > 0
            ):
                reply += f"\n【{user['nick']}】赞了我{user['count']}次"
        if not reply:
            reply = "暂无有效的点赞信息"
        url = await self.text_to_image(reply)
        yield event.image_result(url)
