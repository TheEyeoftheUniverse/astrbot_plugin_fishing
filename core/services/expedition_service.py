import json
import os
import random
import threading
import traceback
from typing import Dict, Any, List, Optional
from datetime import datetime, timedelta
from astrbot.api import logger

from ..repositories.abstract_repository import (
    AbstractUserRepository,
    AbstractInventoryRepository,
    AbstractItemTemplateRepository,
    AbstractLogRepository,
)
from ..utils import get_now


class ExpeditionService:
    """科学考察服务"""

    def __init__(
        self,
        user_repo: AbstractUserRepository,
        inventory_repo: AbstractInventoryRepository,
        item_template_repo: AbstractItemTemplateRepository,
        log_repo: AbstractLogRepository,
        config: Dict[str, Any],
    ):
        self.user_repo = user_repo
        self.inventory_repo = inventory_repo
        self.item_template_repo = item_template_repo
        self.log_repo = log_repo
        self.config = config
        self._expedition_lock = threading.RLock()
        self._settle_timers: Dict[str, threading.Timer] = {}

        # 数据文件路径
        self.data_dir = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(__file__))), "data")
        os.makedirs(self.data_dir, exist_ok=True)
        self.expeditions_file = os.path.join(self.data_dir, "active_expeditions.json")
        self.history_file = os.path.join(self.data_dir, "expedition_history.json")

    def _load_expeditions(self) -> Dict[str, Any]:
        """加载进行中的科考数据"""
        data = self._safe_load_json_with_backup(self.expeditions_file)
        if isinstance(data, dict):
            return data
        logger.error(f"科考数据文件内容类型异常，期望 dict，实际 {type(data)}")
        return {}

    def _save_expeditions(self, expeditions: Dict[str, Any]) -> None:
        """保存科考数据"""
        try:
            with self._expedition_lock:
                if not expeditions:
                    existing = self._try_load_json(self.expeditions_file)
                    if isinstance(existing, dict) and existing:
                        logger.error(
                            "检测到尝试用空对象覆盖非空科考数据，已阻止写入以避免丢档。\n"
                            + "".join(traceback.format_stack(limit=10))
                        )
                        return

                    logger.warning(
                        "即将写入空的科考数据（{}）。若非预期清空，请检查调用链。\n" + "".join(traceback.format_stack(limit=8))
                    )
                self._atomic_write_json_with_backup(self.expeditions_file, expeditions)
        except Exception as e:
            logger.error(f"保存科考数据失败: {e}")

    def _load_history(self) -> Dict[str, Any]:
        """加载科考历史记录"""
        data = self._safe_load_json_with_backup(self.history_file)
        if isinstance(data, dict):
            return data
        logger.error(f"科考历史文件内容类型异常，期望 dict，实际 {type(data)}")
        return {}

    def _save_history(self, history: Dict[str, Any]) -> None:
        """保存科考历史记录"""
        try:
            self._atomic_write_json_with_backup(self.history_file, history)
        except Exception as e:
            logger.error(f"保存科考历史失败: {e}")

    def _safe_load_json_with_backup(self, path: str) -> Any:
        """优先读取主文件；失败时回退读取 .bak。

        额外保护：如果主文件解析成功但内容为空 dict，而 .bak 有非空 dict，
        认为可能发生了异常覆盖，优先返回 .bak。
        """
        main = self._try_load_json(path)
        if isinstance(main, dict) and main:
            return main

        backup_path = f"{path}.bak"
        backup = self._try_load_json(backup_path)

        if isinstance(main, dict) and not main and isinstance(backup, dict) and backup:
            logger.warning(f"检测到 {os.path.basename(path)} 为空，但备份非空，已从备份回退加载")
            return backup

        if main is not None:
            return main
        if backup is not None:
            logger.warning(f"主文件 {os.path.basename(path)} 读取失败，已从备份回退加载")
            return backup
        return {}

    def _try_load_json(self, path: str) -> Any:
        if not os.path.exists(path):
            return None
        try:
            if os.path.getsize(path) <= 0:
                return {}
        except Exception:
            pass

        try:
            with open(path, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception as e:
            logger.error(f"读取JSON失败: {path} - {e}")
            return None

    def _atomic_write_json_with_backup(self, path: str, data: Any) -> None:
        """原子写 JSON，并维护一个 .bak 备份，避免写入中断导致文件被截断。"""
        directory = os.path.dirname(path)
        os.makedirs(directory, exist_ok=True)

        tmp_path = f"{path}.tmp"
        bak_path = f"{path}.bak"
        bak_tmp_path = f"{bak_path}.tmp"

        payload = json.dumps(data, ensure_ascii=False, indent=2)

        # 先备份当前主文件内容（如果存在且可读）
        try:
            if os.path.exists(path):
                with open(path, "rb") as src:
                    existing = src.read()
                if existing:
                    with open(bak_tmp_path, "wb") as bf:
                        bf.write(existing)
                        bf.flush()
                        os.fsync(bf.fileno())
                    os.replace(bak_tmp_path, bak_path)
        except Exception as e:
            logger.warning(f"写入备份失败（将继续保存主文件）: {e}")

        # 原子写主文件
        with open(tmp_path, "w", encoding="utf-8") as f:
            f.write(payload)
            f.flush()
            os.fsync(f.fileno())
        os.replace(tmp_path, path)

    def _prune_storage_to_current_and_last(self) -> None:
        """仅保留所有进行中的科考，以及“每个队长”最近一条已结束科考。

        说明：如果只保留全局最新一条 ended，当多个队伍并行/先后结算时，
        其他队伍的 ended 会被清掉，造成“科考状态查不到上次结果”的体验。
        因此这里按 creator_id 分组，每个队长保留 1 条 ended。
        """
        try:
            with self._expedition_lock:
                expeditions = self._load_expeditions()
                if not expeditions:
                    return

                ended_by_creator: Dict[str, list] = {}
                for exp_id, exp in expeditions.items():
                    if exp.get("status", "active") != "ended":
                        continue
                    creator_id = exp.get("creator_id") or "unknown"
                    ended_at_str = exp.get("ended_at") or exp.get("end_time")
                    try:
                        ended_at = datetime.strptime(ended_at_str, "%Y-%m-%d %H:%M:%S") if ended_at_str else datetime.min
                    except Exception:
                        ended_at = datetime.min
                    ended_by_creator.setdefault(creator_id, []).append((exp_id, ended_at))

                # 对每个队长：仅保留最新一条 ended
                to_delete = []
                for creator_id, entries in ended_by_creator.items():
                    if len(entries) <= 1:
                        continue
                    entries.sort(key=lambda x: x[1], reverse=True)
                    for exp_id, _ in entries[1:]:
                        to_delete.append(exp_id)

                if not to_delete:
                    return

                for exp_id in to_delete:
                    expeditions.pop(exp_id, None)

                self._save_expeditions(expeditions)
        except Exception as e:
            logger.error(f"修剪科考存储失败: {e}")

    def _record_user_expedition_result(self, user_id: str, expedition: Dict[str, Any], reward: Dict[str, Any]) -> None:
        """记录用户的科考结算结果"""
        history = self._load_history()
        
        type_names = {"short": "探险", "medium": "征服", "long": "圣域"}
        
        history[user_id] = {
            "expedition_id": expedition.get("expedition_id", "unknown"),
            "expedition_type": type_names.get(expedition.get("type", ""), expedition.get("type", "")),
            "completion_rate": expedition.get("total_progress", 0),
            "contribution": reward.get("contribution", 0),
            "coins_reward": reward.get("coins", 0),
            "premium_reward": reward.get("premium", 0),
            "settled_at": get_now().strftime("%Y-%m-%d %H:%M:%S")
        }
        
        self._save_history(history)
        logger.info(f"已保存用户 {user_id} 的科考结算记录")

    def _generate_expedition_id(self) -> str:
        """生成科考ID"""
        timestamp = datetime.now().strftime("%Y%m%d%H%M%S")
        return f"EXP{timestamp}{random.randint(100, 999)}"

    def _select_random_fish(self, rarity: int, zone_id: int = 1) -> Optional[Dict[str, Any]]:
        """从指定星级中随机选择一条鱼"""
        fishes = self.item_template_repo.get_fishes_by_rarity(rarity)
        if not fishes:
            return None
        
        selected_fish = random.choice(fishes)
        return {
            "fish_id": selected_fish.fish_id,
            "fish_name": selected_fish.name,
            "rarity": selected_fish.rarity
        }

    def create_expedition(
        self, 
        creator_id: str, 
        expedition_type: str,
        invited_users: List[str] = None
    ) -> Dict[str, Any]:
        """
        创建科考队伍
        
        Args:
            creator_id: 队长用户ID
            expedition_type: 科考类型 (short/medium/long)
            invited_users: 被邀请的用户ID列表
        """
        user = self.user_repo.get_by_id(creator_id)
        if not user:
            return {"success": False, "message": "用户不存在"}

        # 检查是否已在其他科考中
        if self.get_user_expedition(creator_id):
            return {"success": False, "message": "你已经在另一个科考队伍中了"}

        # 确定科考参数
        type_config = {
            "short": {
                "duration_hours": 24, 
                "targets": 100, 
                "base_reward": 100,
                "required_item_id": 35,  # 探险许可证
                "join_cost": 1000000  # 100w金币
            },
            "medium": {
                "duration_hours": 48, 
                "targets": 500, 
                "base_reward": 500,
                "required_item_id": 36,  # 征服许可证
                "join_cost": 5000000  # 500w金币
            },
            "long": {
                "duration_hours": 72, 
                "targets": 1000, 
                "base_reward": 1000,
                "required_item_id": 37,  # 圣域许可证
                "join_cost": 10000000  # 1000w金币
            },
        }

        if expedition_type not in type_config:
            return {"success": False, "message": "科考类型错误，请使用：探险、征服或圣域"}

        config = type_config[expedition_type]

        # 检查并消耗许可证
        required_item_id = config["required_item_id"]
        user_items = self.inventory_repo.get_user_item_inventory(creator_id)
        item_count = user_items.get(required_item_id, 0)
        
        if item_count < 1:
            item_template = self.item_template_repo.get_item_by_id(required_item_id)
            item_name = item_template.name if item_template else "许可证"
            return {"success": False, "message": f"需要消耗1个{item_name}才能发起科考"}
        
        # 消耗许可证
        self.inventory_repo.update_item_quantity(creator_id, required_item_id, -1)
        
        # 生成科考ID和邀请码
        expedition_id = self._generate_expedition_id()
        
        # 随机选择5种目标鱼（1-5星各一种）
        targets = {}
        # 4星和5星鱼的特殊目标数量
        four_star_targets = {"short": 50, "medium": 100, "long": 500}
        five_star_targets = {"short": 10, "medium": 50, "long": 100}
        
        for rarity in range(1, 6):
            fish = self._select_random_fish(rarity)
            if fish:
                # 4星和5星鱼使用特殊的目标数量，其他星级使用通用配置
                if rarity == 5:
                    required_count = five_star_targets[expedition_type]
                elif rarity == 4:
                    required_count = four_star_targets[expedition_type]
                else:
                    required_count = config["targets"]
                    
                targets[f"{rarity}_star"] = {
                    "fish_id": fish["fish_id"],
                    "fish_name": fish["fish_name"],
                    "rarity": rarity,
                    "required": required_count,
                    "caught": 0
                }

        if len(targets) != 5:
            return {"success": False, "message": "无法选择足够的目标鱼类"}

        # 创建科考数据
        now = get_now()
        end_time = now + timedelta(hours=config["duration_hours"])
        
        expedition = {
            "expedition_id": expedition_id,
            "type": expedition_type,
            "start_time": now.strftime("%Y-%m-%d %H:%M:%S"),
            "end_time": end_time.strftime("%Y-%m-%d %H:%M:%S"),
            "creator_id": creator_id,
            "creator_name": user.nickname or f"渔夫{creator_id[-4:]}",
            "base_reward": config["base_reward"],
            "join_cost": config["join_cost"],  # 保存入场费用
            "targets": targets,
            "participants": {
                creator_id: {
                    "user_id": creator_id,
                    "nickname": user.nickname or f"渔夫{creator_id[-4:]}",
                    "joined_at": now.strftime("%Y-%m-%d %H:%M:%S"),
                    "contribution": {
                        "1_star": 0,
                        "2_star": 0,
                        "3_star": 0,
                        "4_star": 0,
                        "5_star": 0
                    }
                }
            },
            "total_progress": 0.0,
            "status": "active",
            "rare_fish_caught": {}  # 记录成员钓起的6~10星鱼ID: {user_id: [fish_ids]}
        }

        # 自动添加被邀请的用户（需要支付入场费）
        join_cost = config["join_cost"]
        failed_invites = []  # 记录无法加入的用户
        
        if invited_users:
            for user_id in invited_users:
                if user_id == creator_id:
                    continue
                    
                invited_user = self.user_repo.get_by_id(user_id)
                if not invited_user:
                    continue
                    
                # 检查用户是否已在其他科考中
                if self.get_user_expedition(user_id):
                    failed_invites.append((invited_user.nickname or f"渔夫{user_id[-4:]}", "已在其他科考中"))
                    continue
                
                # 检查并扣除入场费
                if not invited_user.can_afford(join_cost):
                    failed_invites.append((invited_user.nickname or f"渔夫{user_id[-4:]}", "金币不足"))
                    continue
                
                # 扣除金币
                invited_user.coins -= join_cost
                self.user_repo.update(invited_user)
                
                # 添加到科考队伍
                expedition["participants"][user_id] = {
                    "user_id": user_id,
                    "nickname": invited_user.nickname or f"渔夫{user_id[-4:]}",
                    "joined_at": now.strftime("%Y-%m-%d %H:%M:%S"),
                    "contribution": {
                        "1_star": 0,
                        "2_star": 0,
                        "3_star": 0,
                        "4_star": 0,
                        "5_star": 0
                    }
                }

        # 保存科考数据
        with self._expedition_lock:
            expeditions = self._load_expeditions()
            expeditions[expedition_id] = expedition
            self._save_expeditions(expeditions)

        # 安排一次性自动结算
        self._schedule_settlement(expedition_id, expedition["end_time"])

        # 生成目标鱼列表文本
        targets_text = "\n".join([
            f"  {'⭐' * t['rarity']} {t['fish_name']}：0/{t['required']}"
            for t in targets.values()
        ])

        type_names = {"short": "探险", "medium": "征服", "long": "圣域"}
        
        # 构建返回消息
        success_count = len(expedition["participants"]) - 1  # 减去队长
        message = (f"🔬 {type_names[expedition_type]}科考已发起！\n"
                  f"📋 邀请码：{expedition_id}\n"
                  f"⏰ 截止时间：{end_time.strftime('%m-%d %H:%M')}\n"
                  f"💰 参与费用：{config['join_cost']:,}金币\n"
                  f"🎯 目标鱼类：\n{targets_text}\n\n")
        
        # 添加邀请结果信息
        if invited_users:
            if success_count > 0:
                message += f"✅ {success_count}位成员已自动加入并支付入场费\n"
            if failed_invites:
                message += f"❌ {len(failed_invites)}位成员无法加入：\n"
                for name, reason in failed_invites:
                    message += f"  • {name}（{reason}）\n"
            message += "\n"
        
        message += f"其他成员可使用 /加入科考 {expedition_id} 加入队伍"
        
        return {
            "success": True,
            "message": message,
            "expedition_id": expedition_id
        }

    def join_expedition(self, user_id: str, expedition_id: str) -> Dict[str, Any]:
        """加入科考队伍"""
        user = self.user_repo.get_by_id(user_id)
        if not user:
            return {"success": False, "message": "用户不存在"}

        with self._expedition_lock:
            # 检查是否已在其他科考中
            current_exp = self.get_user_expedition(user_id)
            if current_exp:
                return {"success": False, "message": "你已经在另一个科考队伍中了"}

            # 加载科考数据
            expeditions = self._load_expeditions()
            if expedition_id not in expeditions:
                return {"success": False, "message": "科考不存在或已结束"}

            expedition = expeditions[expedition_id]

            # 检查科考状态
            if expedition["status"] != "active":
                return {"success": False, "message": "该科考已结束"}

            # 检查是否已过期
            end_time = datetime.strptime(expedition["end_time"], "%Y-%m-%d %H:%M:%S")
            now = get_now()
            
            if now > end_time:
                return {"success": False, "message": "该科考已过期"}

            # 检查是否已在队伍中
            if user_id in expedition["participants"]:
                return {"success": False, "message": "你已经在这个科考队伍中了"}

            # 检查并扣除金币
            join_cost = expedition.get("join_cost", 0)
            if not user.can_afford(join_cost):
                return {"success": False, "message": f"金币不足，需要 {join_cost:,} 金币才能加入科考"}
            
            user.coins -= join_cost
            self.user_repo.update(user)

            # 添加成员
            now = get_now()
            expedition["participants"][user_id] = {
                "user_id": user_id,
                "nickname": user.nickname or f"渔夫{user_id[-4:]}",
                "joined_at": now.strftime("%Y-%m-%d %H:%M:%S"),
                "contribution": {
                    "1_star": 0,
                    "2_star": 0,
                    "3_star": 0,
                    "4_star": 0,
                    "5_star": 0
                }
            }

            # 保存
            expeditions[expedition_id] = expedition
            self._save_expeditions(expeditions)

            return {
                "success": True,
                "message": f"✅ 成功加入科考队伍！\n"
                          f"队长：{expedition['creator_name']}\n"
                          f"当前成员：{len(expedition['participants'])}人\n"
                          f"💸 支付了 {join_cost:,} 金币"
            }

    def leave_expedition(self, user_id: str) -> Dict[str, Any]:
        """退出科考队伍"""
        with self._expedition_lock:
            expedition = self.get_user_expedition(user_id)
            if not expedition:
                return {"success": False, "message": "你不在任何科考队伍中"}

            expedition_id = expedition["expedition_id"]
            
            # 队长不能退出
            if user_id == expedition["creator_id"]:
                return {"success": False, "message": "队长不能退出科考，请使用 /结束科考 来结束考察"}

            # 移除成员（保留贡献记录）
            expeditions = self._load_expeditions()
            if expedition_id in expeditions:
                if user_id in expeditions[expedition_id]["participants"]:
                    del expeditions[expedition_id]["participants"][user_id]
                    self._save_expeditions(expeditions)

            return {"success": True, "message": "已退出科考队伍（你的贡献已保留，但不会获得最终奖励）"}

    def get_user_expedition(self, user_id: str) -> Optional[Dict[str, Any]]:
        """获取用户当前参与的科考"""
        expeditions = self._load_expeditions()
        for exp in expeditions.values():
            if user_id in exp["participants"] and exp["status"] == "active":
                return exp
        return None

    def update_expedition_progress(self, expedition_id: str) -> Dict[str, Any]:
        """
        更新科考进度（重新汇总）

        说明：科考贡献已改为“出售鱼类时”写入 participants[*].contribution。
        因此这里不再从钓鱼记录/统计表重算贡献，只做一次汇总（用于定时任务、查看状态、结算前校正）。
        
        Returns:
            更新结果信息
        """
        with self._expedition_lock:
            expeditions = self._load_expeditions()
            if expedition_id not in expeditions:
                return {"success": False, "message": "科考不存在"}

            expedition = expeditions[expedition_id]

            # 重新计算总进度（只汇总已记录的贡献）
            for target_key, target in expedition["targets"].items():
                total_caught = sum(
                    participant["contribution"].get(target_key, 0)
                    for participant in expedition["participants"].values()
                )
                target["caught"] = min(total_caught, target["required"])

            total_caught = sum(t["caught"] for t in expedition["targets"].values())
            total_required = sum(t["required"] for t in expedition["targets"].values())
            expedition["total_progress"] = total_caught / total_required if total_required > 0 else 0

            expeditions[expedition_id] = expedition
            self._save_expeditions(expeditions)

        logger.info(
            f"科考 {expedition_id} 进度已汇总完成，总进度：{expedition['total_progress']*100:.1f}%"
        )
        return {"success": True, "message": "科考进度已更新"}

    def update_expedition_on_sell_fish(self, user_id: str, sold_fish: Dict[int, int]) -> Dict[str, Any]:
        """
        当用户出售鱼时更新科考进度
        
        Args:
            user_id: 用户ID
            sold_fish: 出售的鱼 {fish_id: quantity}
            
        Returns:
            包含更新信息的字典，如果未更新则返回None
        """
        # 获取用户当前科考
        expedition = self.get_user_expedition(user_id)
        if not expedition:
            return None  # 用户不在科考中，无需更新
        
        expedition_id = expedition["expedition_id"]

        with self._expedition_lock:
            expeditions = self._load_expeditions()
            
            if expedition_id not in expeditions:
                return None
            
            expedition = expeditions[expedition_id]
            
            # 检查科考是否已经结束
            now = get_now()
            end_time = datetime.strptime(expedition["end_time"], "%Y-%m-%d %H:%M:%S")
            if now > end_time:
                return None  # 科考已结束，不再接受进度更新
            
            # 初始化稀有鱼记录
            if "rare_fish_caught" not in expedition:
                expedition["rare_fish_caught"] = {}
            if user_id not in expedition["rare_fish_caught"]:
                expedition["rare_fish_caught"][user_id] = []

            # 构建目标鱼ID映射
            target_fish_ids = {target["fish_id"]: key for key, target in expedition["targets"].items()}

            # 检查出售的鱼中是否有目标鱼
            updated_targets = {}  # 记录更新的目标鱼 {fish_name: {quantity: X, progress: "X/Y"}}
            has_target_update = False
            has_rare_update = False

            for fish_id, quantity in sold_fish.items():
                if not quantity or quantity <= 0:
                    continue

                fish_template = self.item_template_repo.get_fish_by_id(fish_id)
                fish_rarity = getattr(fish_template, "rarity", None)

                # 记录6~10星稀有鱼（用于结算事件池），改为“出售触发”写入
                if fish_rarity is not None and fish_rarity >= 6:
                    expedition["rare_fish_caught"][user_id].extend([fish_id] * quantity)
                    has_rare_update = True

                if fish_id in target_fish_ids:
                    target_key = target_fish_ids[fish_id]
                    current_contribution = expedition["participants"][user_id]["contribution"].get(target_key, 0)
                    expedition["participants"][user_id]["contribution"][target_key] = current_contribution + quantity
                    has_target_update = True

                    fish_name = fish_template.name if fish_template else f"鱼{fish_id}"
                    updated_targets[fish_name] = {
                        "quantity": quantity,
                        "target_key": target_key,
                    }
                    logger.info(f"用户 {user_id} 出售了 {quantity} 条目标鱼 {fish_id}，更新科考贡献")

            if not has_target_update and not has_rare_update:
                return None
            
            # 仅当目标鱼贡献变化时才需要重新计算进度
            if has_target_update:
                for target_key, target in expedition["targets"].items():
                    total_caught = sum(
                        participant["contribution"].get(target_key, 0)
                        for participant in expedition["participants"].values()
                    )
                    target["caught"] = min(total_caught, target["required"])

                total_caught = sum(t["caught"] for t in expedition["targets"].values())
                total_required = sum(t["required"] for t in expedition["targets"].values())
                expedition["total_progress"] = total_caught / total_required if total_required > 0 else 0
            
            # 保存更新
            expeditions[expedition_id] = expedition
            self._save_expeditions(expeditions)
        
        # 若没有目标鱼更新，则只记录稀有鱼池，不向外层提示
        if not has_target_update:
            return None

        # 构建返回信息（包含每条鱼的完成进度）
        for fish_name, info in updated_targets.items():
            target_key = info["target_key"]
            target = expedition["targets"][target_key]
            info["progress"] = f"{target['caught']}/{target['required']}"

        logger.info(
            f"科考 {expedition_id} 进度已更新（用户出售鱼触发），总进度：{expedition['total_progress']*100:.1f}%"
        )

        return {"updated": True, "targets": updated_targets, "total_progress": expedition["total_progress"]}

    def get_expedition_status(self, user_id: str) -> Dict[str, Any]:
        """获取用户当前科考的详细状态"""
        # 加载历史记录
        history = self._load_history()
        user_history = history.get(user_id)
        
        # 获取当前科考
        expedition = self.get_user_expedition(user_id)
        
        # 如果既没有历史记录也不在科考中
        if not user_history and not expedition:
            return {"success": False, "message": "你还没有参加过任何科考"}
        
        message_parts = []
        
        # 显示上次科考结算记录
        if user_history:
            message_parts.append("📜 上次科考结算记录")
            message_parts.append("━━━━━━━━━━━━━━━━━━━━")
            message_parts.append(f"🔬 类型：{user_history['expedition_type']}")
            message_parts.append(f"📊 完成度：{user_history['completion_rate'] * 100:.1f}%")
            message_parts.append(f"🎯 贡献：{user_history['contribution']}条")
            message_parts.append(f"💰 金币奖励：{user_history['coins_reward']:,}")
            message_parts.append(f"💎 钻石奖励：{user_history['premium_reward']}")
            message_parts.append(f"⏰ 结算时间：{user_history['settled_at']}")
        
        # 如果当前不在科考中，只返回历史记录
        if not expedition:
            return {
                "success": True,
                "message": "\n".join(message_parts)
            }
        
        # 如果有历史记录，添加分隔符
        if user_history:
            message_parts.append("")
            message_parts.append("")
        
        expedition_id = expedition["expedition_id"]
        
        # 检查科考是否已经超时
        end_time = datetime.strptime(expedition["end_time"], "%Y-%m-%d %H:%M:%S")
        now = get_now()
        
        # 如果科考已超时，自动结算并返回结算信息（不再依赖队长触发）
        if now > end_time:
            logger.info(f"科考 {expedition_id} 已超时，用户 {user_id} 查看状态时触发自动结算")
            settle_result = self._settle_expedition(expedition_id, manual=False)
            
            # 结算后重新加载历史记录，确保本次结算被读取
            history_after = self._load_history()
            user_history_after = history_after.get(user_id)
            combined_parts = []
            if user_history_after:
                combined_parts.append("📜 上次科考结算记录")
                combined_parts.append("━━━━━━━━━━━━━━━━━━━━")
                combined_parts.append(f"🔬 类型：{user_history_after['expedition_type']}")
                combined_parts.append(f"📊 完成度：{user_history_after['completion_rate'] * 100:.1f}%")
                combined_parts.append(f"🎯 贡献：{user_history_after['contribution']}条")
                combined_parts.append(f"💰 金币奖励：{user_history_after['coins_reward']:,}")
                combined_parts.append(f"💎 钻石奖励：{user_history_after['premium_reward']}")
                combined_parts.append(f"⏰ 结算时间：{user_history_after['settled_at']}")
                combined_parts.append("")
            # 追加这次结算报告
            combined_parts.append(settle_result.get("message", ""))
            return {
                "success": True,
                "message": "\n".join(combined_parts)
            }

        # 显示当前科考状态
        message_parts.append(f"🔬 当前科考状态 [{expedition['expedition_id']}]")
        message_parts.append("━━━━━━━━━━━━━━━━━━━━")
        
        # 格式化目标鱼信息
        targets_info = []
        for target in expedition["targets"].values():
            progress_pct = (target["caught"] / target["required"] * 100) if target["required"] > 0 else 0
            bar_length = 10
            filled = int(progress_pct / 10)
            bar = "█" * filled + "░" * (bar_length - filled)
            
            targets_info.append(
                f"  {'⭐' * target['rarity']} {target['fish_name']}: "
                f"{bar} {target['caught']}/{target['required']} ({progress_pct:.0f}%)"
            )

        # 格式化成员贡献
        participants_info = []
        for p in sorted(
            expedition["participants"].values(),
            key=lambda x: sum(x["contribution"].values()),
            reverse=True
        ):
            total_contrib = sum(p["contribution"].values())
            participants_info.append(f"  {p['nickname']}: {total_contrib}条")

        type_names = {"short": "探险", "medium": "征服", "long": "圣域"}
        
        # 计算剩余时间
        remaining = end_time - now
        hours = int(remaining.total_seconds() / 3600)
        minutes = int((remaining.total_seconds() % 3600) / 60)

        message_parts.append(f"📋 类型：{type_names.get(expedition['type'], expedition['type'])}")
        message_parts.append(f"👑 队长：{expedition['creator_name']}")
        message_parts.append(f"👥 成员：{len(expedition['participants'])}人")
        message_parts.append(f"⏰ 剩余时间：{hours}小时{minutes}分钟")
        message_parts.append(f"📊 总进度：{expedition['total_progress'] * 100:.1f}%")
        message_parts.append("")
        message_parts.append("🎯 目标鱼类：")
        message_parts.extend(targets_info)
        message_parts.append("")
        message_parts.append("👤 贡献排行：")
        message_parts.extend(participants_info[:5])

        return {
            "success": True,
            "message": "\n".join(message_parts)
        }

    def test_complete_expedition(self, user_id: str) -> Dict[str, Any]:
        """测试命令：将当前管理员参与的科考强制按100%完成"""
        with self._expedition_lock:
            expedition = self.get_user_expedition(user_id)
            if not expedition:
                return {"success": False, "message": "你不在任何科考队伍中"}
            
            expedition_id = expedition["expedition_id"]
            expeditions = self._load_expeditions()
            
            if expedition_id not in expeditions:
                return {"success": False, "message": "科考不存在"}
            
            exp = expeditions[expedition_id]
            
            # 将所有目标设置为已完成
            for target_key, target in exp["targets"].items():
                target["caught"] = target["required"]
            
            # 设置总进度为100%
            exp["total_progress"] = 1.0
            
            # 保存修改
            expeditions[expedition_id] = exp
            self._save_expeditions(expeditions)
        
        logger.info(f"管理员 {user_id} 将科考 {expedition_id} 强制设置为100%完成")
        
        return {
            "success": True,
            "message": f"✅ 科考 {expedition_id} 已强制设置为100%完成！\n可以使用 /结束科考 命令进行结算。"
        }

    def end_expedition(self, user_id: str) -> Dict[str, Any]:
        """结束科考（仅队长可用）"""
        expedition = self.get_user_expedition(user_id)
        if not expedition:
            return {"success": False, "message": "你不在任何科考队伍中"}

        if user_id != expedition["creator_id"]:
            return {"success": False, "message": "只有队长可以结束科考"}

        # 执行结算
        return self._settle_expedition(expedition["expedition_id"], manual=True)

    def _settle_expedition(self, expedition_id: str, manual: bool = False) -> Dict[str, Any]:
        """结算科考"""
        with self._expedition_lock:
            expeditions = self._load_expeditions()
            if expedition_id not in expeditions:
                return {"success": False, "message": "科考不存在"}

            expedition = expeditions[expedition_id]
            if expedition.get("status") == "ended":
                return {"success": True, "message": expedition.get("settlement_report", "科考已结算")}
            
            # 在结算前强制汇总一次进度，确保包含最新的出售贡献
            logger.info(f"科考 {expedition_id} 结算前强制更新进度")
            self.update_expedition_progress(expedition_id)
            # 重新加载最新数据
            expeditions = self._load_expeditions()
            expedition = expeditions[expedition_id]
            
            # 计算总贡献
            total_contribution = 0
            for participant in expedition["participants"].values():
                total_contribution += sum(participant["contribution"].values())

            if total_contribution == 0:
                # 没有任何贡献：仍记录结算历史（贡献/奖励均为0），便于队长和成员查询“上次科考”
                completion_rate = expedition.get("total_progress", 0)
                for user_id, participant in expedition["participants"].items():
                    reward_stub = {
                        "nickname": participant.get("nickname", ""),
                        "contribution": 0,
                        "coins": 0,
                        "premium": 0,
                    }
                    self._record_user_expedition_result(user_id, expedition, reward_stub)
                # 标记为已结束并保留记录，不删除
                expedition["status"] = "ended"
                expedition["ended_at"] = get_now().strftime("%Y-%m-%d %H:%M:%S")
                expeditions[expedition_id] = expedition
                self._save_expeditions(expeditions)
                # 修剪：仅保留进行中和最近一条已结束科考
                self._prune_storage_to_current_and_last()
                return {
                    "success": True,
                    "message": "科考已结束（无人贡献，无奖励发放）"
                }

            # 检查星级完成度并触发事件
            completed_rarities = []
            for target_key, target in expedition["targets"].items():
                if target["caught"] >= target["required"]:
                    completed_rarities.append(target["rarity"])
            
            # 去重并排序
            completed_rarities = sorted(set(completed_rarities))
            
            # 触发事件判定
            event_results = []
            for rarity in completed_rarities:
                event_result = self._trigger_rarity_event(expedition, rarity)
                if event_result:
                    event_results.append(event_result)
            
            # 计算队伍总奖励
            completion_rate = expedition["total_progress"]
            
            # 钻石奖励基础值
            type_premium_base = {"short": 1000, "medium": 5000, "long": 10000}
            base_premium = type_premium_base.get(expedition["type"], 1000)
            total_premium = int(base_premium * completion_rate)
            
            # 计算拼手气红包奖池（参与人数 × 入场费）
            join_cost = expedition.get("join_cost", 0)
            participant_count = len(expedition["participants"])
            pool_coins = int(participant_count * join_cost)
            
            # 随机分配奖池金币（拼手气红包算法）
            random_coin_rewards = self._distribute_lucky_money(pool_coins, participant_count)

            # 分配奖励给各成员
            rewards = {}
            reward_index = 0
            for user_id, participant in expedition["participants"].items():
                user_contribution = sum(participant["contribution"].values())
                if user_contribution > 0:
                    # 按贡献比例分配钻石
                    personal_premium = max(1, int(total_premium * (user_contribution / total_contribution)))
                    
                    # 获取随机金币奖励（拼手气红包）
                    random_coins = random_coin_rewards[reward_index] if reward_index < len(random_coin_rewards) else 0
                    reward_index += 1
                    
                    # 发放金币和钻石
                    user = self.user_repo.get_by_id(user_id)
                    if user:
                        # 只有随机金币奖励
                        user.coins += random_coins
                        
                        # 钻石奖励
                        user.premium_currency += personal_premium
                        
                        self.user_repo.update(user)
                        
                        rewards[user_id] = {
                            "nickname": participant["nickname"],
                            "contribution": user_contribution,
                            "coins": random_coins,
                            "premium": personal_premium
                        }
                        
                        # 保存用户的科考结算记录
                        self._record_user_expedition_result(user_id, expedition, rewards[user_id])

            # 确保所有参与者（即使贡献为0）也有“上次科考”历史记录可查
            for user_id, participant in expedition["participants"].items():
                if user_id in rewards:
                    continue
                reward_stub = {
                    "nickname": participant.get("nickname", ""),
                    "contribution": 0,
                    "coins": 0,
                    "premium": 0,
                }
                self._record_user_expedition_result(user_id, expedition, reward_stub)

            # 生成结算报告
            type_names = {"short": "探险", "medium": "征服", "long": "圣域"}
            report_lines = [
                f"🎉 {type_names.get(expedition['type'], '')}科考已结束！",
                f"━━━━━━━━━━━━━━━━━━━━",
                f"📊 完成度：{completion_rate * 100:.1f}%",
                f"💎 总钻石奖励：{total_premium}",
                f"🎲 拼手气奖池：{pool_coins:,}金币"
            ]
            
            # 添加事件结果
            if event_results:
                report_lines.append("")
                report_lines.append("✨ 特殊事件：")
                for event in event_results:
                    report_lines.append(event)
            
            report_lines.append("")
            report_lines.append("👤 个人奖励：")

            for reward in sorted(rewards.values(), key=lambda x: x["contribution"], reverse=True):
                report_lines.append(
                    f"  {reward['nickname']}: "
                    f"{reward['coins']:,}金币 + "
                    f"{reward['premium']}钻石"
                )

            # 标记为已结束并保留记录（包含结算报告）
            expedition["status"] = "ended"
            expedition["ended_at"] = get_now().strftime("%Y-%m-%d %H:%M:%S")
            expedition["settlement_report"] = "\n".join(report_lines)
            expeditions[expedition_id] = expedition
            self._save_expeditions(expeditions)
            self._cancel_settlement_timer(expedition_id)
            # 修剪：仅保留进行中和最近一条已结束科考
            self._prune_storage_to_current_and_last()

            return {
                "success": True,
                "message": "\n".join(report_lines),
                "rewards": rewards
            }

    def schedule_active_expeditions(self) -> None:
        """为当前进行中的科考安排一次性结算任务（仅在启动时调用）"""
        expeditions = self._load_expeditions()
        for exp_id, exp in expeditions.items():
            if exp.get("status", "active") != "active":
                continue
            end_time = exp.get("end_time")
            if not end_time:
                continue
            self._schedule_settlement(exp_id, end_time)

    def _schedule_settlement(self, expedition_id: str, end_time_str: str) -> None:
        """安排单次结算定时器"""
        try:
            with self._expedition_lock:
                if expedition_id in self._settle_timers:
                    return
            end_time = datetime.strptime(end_time_str, "%Y-%m-%d %H:%M:%S")
            now = get_now()
            delay = max(0, (end_time - now).total_seconds())

            def _settle_job():
                try:
                    self._settle_expedition(expedition_id, manual=False)
                except Exception as e:
                    logger.error(f"科考自动结算失败: {e}")

            timer = threading.Timer(delay, _settle_job)
            timer.daemon = True
            with self._expedition_lock:
                self._settle_timers[expedition_id] = timer
            timer.start()
        except Exception as e:
            logger.error(f"安排科考结算失败: {e}")

    def _cancel_settlement_timer(self, expedition_id: str) -> None:
        """取消定时器"""
        with self._expedition_lock:
            timer = self._settle_timers.pop(expedition_id, None)
        if timer:
            try:
                timer.cancel()
            except Exception:
                pass

    def _distribute_lucky_money(self, total_amount: int, count: int) -> list:
        """拼手气红包算法：随机分配金额
        
        Args:
            total_amount: 总金额
            count: 人数
            
        Returns:
            每个人获得的金额列表
        """
        if count <= 0 or total_amount <= 0:
            return []
        
        if count == 1:
            return [total_amount]
        
        # 使用二倍均值算法
        amounts = []
        remaining = total_amount
        
        for i in range(count - 1):
            # 每次随机分配 [1, 剩余金额/(剩余人数)*2] 之间的金额
            # 确保每个人至少得到1金币
            max_amount = int(remaining / (count - i) * 2)
            if max_amount < 1:
                max_amount = 1
            
            amount = random.randint(1, max(1, max_amount))
            amounts.append(amount)
            remaining -= amount
        
        # 最后一个人获得剩余所有金额
        amounts.append(max(0, remaining))
        
        # 随机打乱顺序，增加随机性
        random.shuffle(amounts)
        
        return amounts

    def _trigger_rarity_event(self, expedition: Dict[str, Any], rarity: int) -> Optional[str]:
        """触发星级完成事件判定
        
        Args:
            expedition: 科考数据
            rarity: 完成的星级
            
        Returns:
            事件结果文本，如果没有触发事件则返回None
        """
        import random
        
        # 三种事件及其触发率
        events = [
            {"name": "quantum_imaging", "rate": 0.10},  # 量子成像效应
            {"name": "spiritual_evolution", "rate": 0.08},  # 天材地宝
            {"name": "abyss_vortex", "rate": 0.12}  # 深渊漩涡
        ]
        
        # 随机判定是否触发事件
        rand = random.random()
        cumulative_rate = 0
        triggered_event = None
        
        for event in events:
            cumulative_rate += event["rate"]
            if rand < cumulative_rate:
                triggered_event = event["name"]
                break
        
        if not triggered_event:
            return None
        
        # 根据科考类型确定影响人数
        participant_count = {"short": 1, "medium": 2, "long": 3}.get(expedition["type"], 1)
        fish_count = {"short": 1, "medium": 2, "long": 3}.get(expedition["type"], 1)
        
        # 获取参与者列表
        participant_ids = list(expedition["participants"].keys())
        if not participant_ids:
            return None
        
        # 随机选择受影响的成员
        selected_users = random.sample(participant_ids, min(participant_count, len(participant_ids)))
        
        # 执行事件效果
        if triggered_event == "quantum_imaging":
            # ①量子成像效应：随机成员获得其他成员钓起的6~10星鱼
            result_lines = []
            rare_fish_pool = []
            
            # 收集所有成员钓起的稀有鱼
            for user_id in participant_ids:
                if user_id in expedition.get("rare_fish_caught", {}):
                    rare_fish_pool.extend(expedition["rare_fish_caught"][user_id])
            
            if rare_fish_pool:
                for user_id in selected_users:
                    user = self.user_repo.get_by_id(user_id)
                    if user:
                        # 随机选择鱼
                        selected_fish = random.choices(rare_fish_pool, k=min(fish_count, len(rare_fish_pool)))
                        
                        # 添加到用户鱼塘
                        from core.services.aquarium_service import AquariumService
                        aquarium_service = AquariumService(self.user_repo, self.item_template_repo)
                        
                        for fish_id in selected_fish:
                            aquarium_service.add_fish_to_aquarium(user_id, fish_id)
                        
                        nickname = expedition["participants"][user_id]["nickname"]
                        result_lines.append(f"  {nickname} 观测到了{len(selected_fish)}条稀有鱼")
                
                return f"  🌟 量子成像效应！在见到科考同伴的渔获时，产生了量子成像效应：\n" + "\n".join(result_lines)
        
        elif triggered_event == "spiritual_evolution":
            # ②天材地宝：随机成员鱼塘中的鱼全部替换成高品质
            result_lines = []
            
            for user_id in selected_users:
                user = self.user_repo.get_by_id(user_id)
                if user and user.aquarium:
                    from core.services.aquarium_service import AquariumService
                    aquarium_service = AquariumService(self.user_repo, self.item_template_repo)
                    
                    # 将鱼塘中所有鱼的品质提升为"优良"或"完美"
                    improved_count = 0
                    for fish_entry in user.aquarium:
                        if fish_entry.get("quality", "普通") not in ["优良", "完美"]:
                            fish_entry["quality"] = random.choice(["优良", "完美"])
                            improved_count += 1
                    
                    if improved_count > 0:
                        self.user_repo.update(user)
                        nickname = expedition["participants"][user_id]["nickname"]
                        result_lines.append(f"  {nickname} 的鱼塘中{improved_count}条鱼发生了进化")
            
            if result_lines:
                return f"  ✨ 天材地宝！路经天材地宝，此处的鱼被四溢的灵气滋养：\n" + "\n".join(result_lines)
        
        elif triggered_event == "abyss_vortex":
            # ③深渊漩涡：随机成员获得5星鱼
            fish_count_by_type = {"short": 10, "medium": 20, "long": 30}
            total_fish = fish_count_by_type.get(expedition["type"], 10)
            
            result_lines = []
            
            # 获取所有5星鱼的模板
            all_fish = self.item_template_repo.get_all_fish()
            five_star_fish = [f for f in all_fish if f.rarity == 5]
            
            if five_star_fish:
                for user_id in selected_users:
                    user = self.user_repo.get_by_id(user_id)
                    if user:
                        # 随机选择5星鱼
                        selected_fish_ids = [random.choice(five_star_fish).fish_id for _ in range(total_fish)]
                        
                        # 添加到背包
                        for fish_id in selected_fish_ids:
                            self.inventory_repo.add_or_update_item(user_id, fish_id, 1)
                        
                        nickname = expedition["participants"][user_id]["nickname"]
                        result_lines.append(f"  {nickname} 获得了{total_fish}条5星鱼")
                
                return f"  🌀 深渊漩涡！成员跌入了海中心的深渊漩涡，却又在凌晨出现在甲板上：\n" + "\n".join(result_lines)
        
        return None

    def get_all_active_expeditions(self) -> List[Dict[str, Any]]:
        """获取所有进行中的科考（用于WebUI显示）"""
        expeditions = self._load_expeditions()
        active_list = []
        
        for exp in expeditions.values():
            if exp["status"] == "active":
                # 计算剩余时间
                end_time = datetime.strptime(exp["end_time"], "%Y-%m-%d %H:%M:%S")
                now = get_now()
                remaining = end_time - now
                
                if remaining.total_seconds() > 0:
                    active_list.append({
                        "expedition_id": exp["expedition_id"],
                        "type": exp["type"],
                        "creator_name": exp["creator_name"],
                        "member_count": len(exp["participants"]),
                        "total_progress": exp["total_progress"],
                        "targets": exp["targets"],
                        "participants": exp["participants"],
                        "remaining_hours": int(remaining.total_seconds() / 3600),
                        "remaining_minutes": int((remaining.total_seconds() % 3600) / 60)
                    })
        
        return active_list

    def auto_settle_expired_expeditions(self) -> int:
        """自动结算所有已超时的科考，返回结算数量"""
        settled_count = 0
        try:
            with self._expedition_lock:
                expeditions = self._load_expeditions()
                now = get_now()
                expired_ids = []

                for exp_id, exp in expeditions.items():
                    if exp.get("status", "active") != "active":
                        continue
                    end_time_str = exp.get("end_time")
                    if not end_time_str:
                        continue
                    try:
                        end_time = datetime.strptime(end_time_str, "%Y-%m-%d %H:%M:%S")
                    except Exception:
                        continue
                    if now > end_time:
                        expired_ids.append(exp_id)

            for exp_id in expired_ids:
                result = self._settle_expedition(exp_id, manual=False)
                if result and result.get("success"):
                    settled_count += 1
        except Exception as e:
            logger.error(f"自动结算科考失败: {e}")

        return settled_count
