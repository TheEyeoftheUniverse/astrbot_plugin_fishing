from astrbot.api import logger
from astrbot.core.message.components import At
from typing import Dict, Any
from ..core.services.expedition_service import ExpeditionService


class ExpeditionHandlers:
    """科考命令处理器"""

    def __init__(self, expedition_service: ExpeditionService):
        self.expedition_service = expedition_service

    async def start_expedition(self, plugin, event) -> Dict[str, Any]:
        """
        发起科考
        命令：/发起科考 <探险/征服/圣域> [@用户1 @用户2 ...]
        """
        try:
            msg_text = event.message_str.strip()
            parts = msg_text.split()
            
            if len(parts) < 2:
                return {
                    "success": False,
                    "message": "用法：/发起科考 <探险/征服/圣域> [@用户1 @用户2 ...]\n"
                              "示例：/发起科考 探险\n"
                              "示例：/发起科考 征服 @张三 @李四"
                }
            
            # 解析科考类型
            type_map = {"探险": "short", "征服": "medium", "圣域": "long"}
            exp_type_str = parts[1]
            exp_type = type_map.get(exp_type_str)
            
            if not exp_type:
                return {
                    "success": False,
                    "message": "科考类型错误，请选择：探险、征服或圣域"
                }
            
            # 解析被邀请的用户（从At组件中提取）
            invited_user_ids = []
            message_obj = event.message_obj
            
            # 首先尝试从message_obj中获取At组件（推荐方式）
            if hasattr(message_obj, "message"):
                for comp in message_obj.message:
                    if isinstance(comp, At):
                        # 排除机器人本身的id
                        if hasattr(message_obj, 'self_id') and comp.qq != message_obj.self_id:
                            invited_user_ids.append(str(comp.qq))
                        elif not hasattr(message_obj, 'self_id'):
                            invited_user_ids.append(str(comp.qq))
            
            # 如果没有获取到，尝试从原始消息中用正则提取（备用方案）
            if not invited_user_ids:
                import re
                raw_message = event.raw_message if hasattr(event, 'raw_message') else msg_text
                at_pattern = r'\[CQ:at,qq=(\d+)\]'
                matches = re.findall(at_pattern, raw_message)
                if matches:
                    invited_user_ids = matches
            
            if invited_user_ids:
                logger.info(f"从消息中提取到被邀请用户: {invited_user_ids}")
            
            # 创建科考
            user_id = event.get_sender_id()
            result = self.expedition_service.create_expedition(
                creator_id=user_id,
                expedition_type=exp_type,
                invited_users=invited_user_ids
            )
            
            return result
            
        except Exception as e:
            logger.error(f"发起科考失败: {e}", exc_info=True)
            return {"success": False, "message": f"发起科考失败：{str(e)}"}

    async def join_expedition(self, plugin, event) -> Dict[str, Any]:
        """
        加入科考
        命令：/加入科考 <邀请码>
        """
        try:
            msg_text = event.message_str.strip()
            parts = msg_text.split()
            
            if len(parts) < 2:
                return {
                    "success": False,
                    "message": "用法：/加入科考 <邀请码>\n示例：/加入科考 EXP20260108001"
                }
            
            expedition_id = parts[1].strip()
            user_id = event.get_sender_id()
            
            result = self.expedition_service.join_expedition(user_id, expedition_id)
            return result
            
        except Exception as e:
            logger.error(f"加入科考失败: {e}", exc_info=True)
            return {"success": False, "message": f"加入科考失败：{str(e)}"}

    async def leave_expedition(self, plugin, event) -> Dict[str, Any]:
        """
        退出科考
        命令：/退出科考
        """
        try:
            user_id = event.get_sender_id()
            result = self.expedition_service.leave_expedition(user_id)
            return result
            
        except Exception as e:
            logger.error(f"退出科考失败: {e}", exc_info=True)
            return {"success": False, "message": f"退出科考失败：{str(e)}"}

    async def expedition_status(self, plugin, event) -> Dict[str, Any]:
        """
        查看科考状态
        命令：/科考状态
        """
        try:
            user_id = event.get_sender_id()
            
            # 先更新当前科考的进度数据
            current_exp = self.expedition_service.get_user_expedition(user_id)
            if current_exp:
                expedition_id = current_exp.get("expedition_id")
                if expedition_id:
                    try:
                        self.expedition_service.update_expedition_progress(expedition_id)
                    except Exception as update_error:
                        logger.warning(f"更新科考进度失败: {update_error}")
            
            result = self.expedition_service.get_expedition_status(user_id)
            return result
            
        except Exception as e:
            logger.error(f"查看科考状态失败: {e}", exc_info=True)
            return {"success": False, "message": f"查看科考状态失败：{str(e)}"}

    async def end_expedition(self, plugin, event) -> Dict[str, Any]:
        """
        结束科考（仅队长）
        命令：/结束科考
        """
        try:
            user_id = event.get_sender_id()
            result = self.expedition_service.end_expedition(user_id)
            return result
            
        except Exception as e:
            logger.error(f"结束科考失败: {e}", exc_info=True)
            return {"success": False, "message": f"结束科考失败：{str(e)}"}

    async def expedition_help(self, plugin, event) -> Dict[str, Any]:
        """
        查看科考帮助
        命令：,科考帮助
        """
        help_text = """🔬 科学考察系统帮助

━━━━ 📋 科考类型 ━━━━
🌊 探险（24小时）
    ▸ 需要：探险许可证
  ▸ 入场费：100万金币
  ▸ 目标：1-3星各100条 | 4星50条 | 5星10条
  ▸ 钻石奖池：1000钻石

⚔️ 征服（48小时）
    ▸ 需要：征服许可证
  ▸ 入场费：500万金币
  ▸ 目标：1-3星各500条 | 4星100条 | 5星50条
  ▸ 钻石奖池：5000钻石

👑 圣域（72小时）
    ▸ 需要：圣域许可证
  ▸ 入场费：1000万金币
  ▸ 目标：1-3星各1000条 | 4星500条 | 5星100条
  ▸ 钻石奖池：10000钻石

━━━━ 🎮 参与规则 ━━━━
▸ 发起者消耗对应许可证创建科考
▸ 参与者支付金币入场费加入队伍
▸ 每个玩家同时只能参与一个科考
▸ 队长可提前结束科考进行结算
▸ 到期后自动结算奖励

━━━━ 🎯 科考目标 ━━━━
▸ 系统随机选择5种鱼（1-5星各一种）
▸ 队伍成员需要出售指定数量的目标鱼（出售时计入贡献）
▸ 高星级鱼类目标数量较少，降低难度
▸ 进度在出售目标鱼时实时更新

━━━━ 💰 奖励分配 ━━━━
【钻石奖励】按贡献比例分配
  个人钻石 = 钻石奖池 × 完成度 × (个人贡献/总贡献)
  
【金币奖励】拼手气红包
  奖池金额 = 参与人数 × 入场费 × 完成度
  采用随机分配算法，手气拼人品！

━━━━ ✨ 特殊事件 ━━━━
当某个星级完成度达100%时，有概率特殊事件。

━━━━ 📝 相关命令 ━━━━
,发起科考 <探险/征服/圣域> [@用户]
,加入科考 <邀请码>
,退出科考
,科考状态
,结束科考（仅队长）
,科考帮助

━━━━ ⚠️ 注意事项 ━━━━
▸ 队长不能中途退出，只能结束科考
▸ 中途退出的成员不会获得奖励
▸ 贡献会保留但无法获得结算奖励
▸ 许可证可通过商店或抽奖获得
▸ 入场费将进入奖池，完成度越高回报越高"""
        
        return {"success": True, "message": help_text}

    async def test_expedition(self, plugin, event) -> Dict[str, Any]:
        """
        测试命令：强制将当前科考设置为100%完成
        命令：/测试科考
        """
        user_id = event.get_sender_id()
        result = self.expedition_service.test_complete_expedition(user_id)
        return result


# 命令注册辅助函数
def register_expedition_handlers(plugin, expedition_service: ExpeditionService):
    """注册科考相关命令"""
    handlers = ExpeditionHandlers(expedition_service)
    
    @plugin.cmd_handler("/发起科考", "发起科考队伍", example="/发起科考 探险 [@用户1 @用户2]")
    async def cmd_start_expedition(plugin, event):
        result = await handlers.start_expedition(plugin, event)
        await plugin.send_text(result["message"], event)
    
    @plugin.cmd_handler("/加入科考", "加入科考队伍", example="/加入科考 EXP20260108001")
    async def cmd_join_expedition(plugin, event):
        result = await handlers.join_expedition(plugin, event)
        await plugin.send_text(result["message"], event)
    
    @plugin.cmd_handler("/退出科考", "退出当前科考队伍", example="/退出科考")
    async def cmd_leave_expedition(plugin, event):
        result = await handlers.leave_expedition(plugin, event)
        await plugin.send_text(result["message"], event)
    
    @plugin.cmd_handler("/科考状态", "查看当前科考进度", example="/科考状态")
    async def cmd_expedition_status(plugin, event):
        result = await handlers.expedition_status(plugin, event)
        await plugin.send_text(result["message"], event)
    
    @plugin.cmd_handler("/结束科考", "结束科考并结算（仅队长）", example="/结束科考")
    async def cmd_end_expedition(plugin, event):
        result = await handlers.end_expedition(plugin, event)
        await plugin.send_text(result["message"], event)
    
    @plugin.cmd_handler("/科考帮助", "查看科考系统帮助", example="/科考帮助")
    async def cmd_expedition_help(plugin, event):
        result = await handlers.expedition_help(plugin, event)
        await plugin.send_text(result["message"], event)
    
    logger.info("科考命令已注册")
