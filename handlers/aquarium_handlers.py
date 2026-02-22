from astrbot.api.event import AstrMessageEvent
from ..utils import format_rarity_display
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from ..main import FishingPlugin


async def aquarium(self: "FishingPlugin", event: AstrMessageEvent):
    """水族箱主命令：
    - "水族箱": 显示水族箱列表
    - "水族箱 帮助": 显示帮助
    """
    args = event.message_str.strip().split()
    if len(args) >= 2 and args[1] == "帮助":
        async for r in aquarium_help(self, event):
            yield r
        return

    user_id = self._get_effective_user_id(event)
    result = self.aquarium_service.get_user_aquarium(user_id)

    if not result["success"]:
        yield event.plain_result(f"❌ {result['message']}")
        return

    fishes = result["fishes"]
    stats = result["stats"]

    if not fishes:
        yield event.plain_result("🐠 您的水族箱是空的，快去钓鱼吧！")
        return

    # 按稀有度分组
    fishes_by_rarity = {}
    for fish in fishes:
        rarity = fish.get("rarity", "未知")
        if rarity not in fishes_by_rarity:
            fishes_by_rarity[rarity] = []
        fishes_by_rarity[rarity].append(fish)

    # 构造输出信息
    message = "【🐠 水族箱】：\n"

    for rarity in sorted(fishes_by_rarity.keys(), reverse=True):
        if fish_list := fishes_by_rarity[rarity]:
            message += f"\n {format_rarity_display(rarity)}：\n"
            for fish in fish_list:
                fish_id = int(fish.get('fish_id', 0) or 0)
                quality_level = fish.get('quality_level', 0)
                # 生成带品质标识的FID
                if quality_level == 1:
                    fcode = f"F{fish_id}H" if fish_id else "F0H"  # H代表✨高品质
                else:
                    fcode = f"F{fish_id}" if fish_id else "F0"   # 普通品质
                # 显示品质信息
                quality_display = ""
                if quality_level == 1:
                    quality_display = " ✨高品质"
                message += f"  - {fish['name']}{quality_display} x  {fish['quantity']} （{fish['actual_value']}金币 / 个） ID: {fcode}\n"

    message += f"\n🐟 总鱼数：{stats['total_count']} / {stats['capacity']} 条\n"
    message += f"💰 总价值：{stats['total_value']} 金币\n"
    message += f"📦 剩余空间：{stats['available_space']} 条\n"

    yield event.plain_result(message)


async def add_to_aquarium(self: "FishingPlugin", event: AstrMessageEvent):
    """将鱼从鱼塘添加到水族箱"""
    user_id = self._get_effective_user_id(event)
    args = event.message_str.split(" ")
    
    if len(args) < 2:
        yield event.plain_result("❌ 用法：/放入水族箱 <鱼ID> [数量]\n💡 使用「水族箱」命令查看水族箱中的鱼")
        return

    try:
        # 解析鱼ID（支持F开头的短码，包括品质标识）
        fish_token = args[1].strip().upper()
        quality_level = 0  # 默认普通品质
        
        if fish_token.startswith('F'):
            # 检查是否有品质标识H
            if fish_token.endswith('H'):
                quality_level = 1  # ✨高品质
                fish_id = int(fish_token[1:-1])  # 去掉F前缀和H后缀
            else:
                fish_id = int(fish_token[1:])  # 去掉F前缀
        else:
            fish_id = int(fish_token)
        
        quantity = 1
        if len(args) >= 3:
            quantity = int(args[2])
            if quantity <= 0:
                yield event.plain_result("❌ 数量必须是正整数")
                return
    except ValueError:
        yield event.plain_result("❌ 鱼ID格式错误！请使用F开头的短码（如F3、F3H）或纯数字ID")
        return

    result = self.aquarium_service.add_fish_to_aquarium(user_id, fish_id, quantity, quality_level)
    
    if result["success"]:
        yield event.plain_result(f"✅ {result['message']}")
    else:
        yield event.plain_result(f"❌ {result['message']}")


async def remove_from_aquarium(self: "FishingPlugin", event: AstrMessageEvent):
    """将鱼从水族箱移回鱼塘"""
    user_id = self._get_effective_user_id(event)
    args = event.message_str.split(" ")
    
    if len(args) < 2:
        yield event.plain_result("❌ 用法：/移出水族箱 <鱼ID> [数量]\n💡 使用「水族箱」命令查看水族箱中的鱼")
        return

    try:
        # 解析鱼ID（支持F开头的短码，包括品质标识）
        fish_token = args[1].strip().upper()
        quality_level = 0  # 默认普通品质
        
        if fish_token.startswith('F'):
            # 检查是否有品质标识H
            if fish_token.endswith('H'):
                quality_level = 1  # ✨高品质
                fish_id = int(fish_token[1:-1])  # 去掉F前缀和H后缀
            else:
                fish_id = int(fish_token[1:])  # 去掉F前缀
        else:
            fish_id = int(fish_token)
        
        quantity = 1
        if len(args) >= 3:
            quantity = int(args[2])
            if quantity <= 0:
                yield event.plain_result("❌ 数量必须是正整数")
                return
    except ValueError:
        yield event.plain_result("❌ 鱼ID格式错误！请使用F开头的短码（如F3、F3H）或纯数字ID")
        return

    result = self.aquarium_service.remove_fish_from_aquarium(user_id, fish_id, quantity, quality_level)
    
    if result["success"]:
        yield event.plain_result(f"✅ {result['message']}")
    else:
        yield event.plain_result(f"❌ {result['message']}")


async def upgrade_aquarium(self: "FishingPlugin", event: AstrMessageEvent):
    """升级水族箱容量"""
    user_id = self._get_effective_user_id(event)
    # 直接尝试升级，失败时会返回具体原因（包含所需费用）
    result = self.aquarium_service.upgrade_aquarium(user_id)
    
    if result["success"]:
        yield event.plain_result(f"✅ {result['message']}")
    else:
        yield event.plain_result(f"❌ {result['message']}")


    # 过度信息命令删除：在升级操作中按需提示


async def aquarium_help(self: "FishingPlugin", event: AstrMessageEvent):
    """水族箱帮助信息"""
    message = """【🐠 水族箱系统帮助】：

🔹 水族箱是一个安全的存储空间，鱼放在里面不会被偷
🔹 默认容量50条，可以通过升级增加容量
🔹 从市场购买的鱼默认放入水族箱
🔹 可以正常上架和购买

📋 可用命令：
• /水族箱 - 查看水族箱中的鱼
• /放入水族箱 <鱼ID> [数量] - 将鱼从鱼塘放入水族箱
• /移出水族箱 <鱼ID> [数量] - 将鱼从水族箱移回鱼塘
• /放入稀有度 <稀有度> - 将指定稀有度的所有鱼放入水族箱
• /移出稀有度 <稀有度> - 将指定稀有度的所有鱼移回鱼塘
• /升级水族箱 - 升级水族箱容量
• /水族箱 帮助 - 显示此帮助信息

💡 提示：使用「水族箱」命令查看鱼ID
💡 稀有度范围：1-10 (1⭐~10⭐)"""
    
    yield event.plain_result(message)


async def add_rarity_to_aquarium(self: "FishingPlugin", event: AstrMessageEvent):
    """按稀有度将鱼从鱼塘批量放入水族箱"""
    user_id = self._get_effective_user_id(event)
    args = event.message_str.split(" ")
    
    if len(args) < 2:
        yield event.plain_result("❌ 用法：/放入稀有度 <稀有度>\n💡 例如：/放入稀有度 3 （将所有3星鱼放入水族箱）")
        return
    
    try:
        rarity = int(args[1])
        if rarity < 1 or rarity > 10:
            yield event.plain_result("❌ 稀有度必须在1-10之间")
            return
    except ValueError:
        yield event.plain_result("❌ 稀有度必须是数字（1-10）")
        return
    
    # 获取鱼塘中该稀有度的所有鱼
    inventory_result = self.inventory_service.get_user_fish_pond(user_id)
    if not inventory_result.get("success"):
        yield event.plain_result(f"❌ 获取鱼塘信息失败")
        return
    
    fishes = inventory_result.get("fishes", [])
    target_fishes = [f for f in fishes if f.get("rarity") == rarity]
    
    if not target_fishes:
        yield event.plain_result(f"❌ 鱼塘中没有{rarity}星稀有度的鱼")
        return
    
    # 批量添加到水族箱
    total_moved = 0
    high_quality_count = 0
    success_count = 0
    failed_items = []
    
    for fish in target_fishes:
        fish_id = fish.get("fish_id")
        quantity = fish.get("quantity", 0)
        quality_level = fish.get("quality_level", 0)
        
        if quantity > 0:
            result = self.aquarium_service.add_fish_to_aquarium(user_id, fish_id, quantity, quality_level)
            if result.get("success"):
                total_moved += quantity
                if quality_level == 1:
                    high_quality_count += quantity
                success_count += 1
            else:
                failed_items.append(f"{fish.get('name')}({result.get('message')})")
    
    # 构建结果消息
    message = f"✅ 成功将 {success_count} 种{rarity}星鱼（共{total_moved}条）放入水族箱"
    if high_quality_count > 0:
        message += f"\n✨ 其中包含 {high_quality_count} 条高品质鱼"
    if failed_items:
        message += f"\n\n⚠️ 以下鱼类移动失败：\n" + "\n".join(f"  - {item}" for item in failed_items[:5])
        if len(failed_items) > 5:
            message += f"\n  ... 还有{len(failed_items)-5}项"
    
    yield event.plain_result(message)


async def remove_rarity_from_aquarium(self: "FishingPlugin", event: AstrMessageEvent):
    """按稀有度将鱼从水族箱批量移回鱼塘"""
    user_id = self._get_effective_user_id(event)
    args = event.message_str.split(" ")
    
    if len(args) < 2:
        yield event.plain_result("❌ 用法：/移出稀有度 <稀有度>\n💡 例如：/移出稀有度 1 （将所有1星鱼移回鱼塘）")
        return
    
    try:
        rarity = int(args[1])
        if rarity < 1 or rarity > 10:
            yield event.plain_result("❌ 稀有度必须在1-10之间")
            return
    except ValueError:
        yield event.plain_result("❌ 稀有度必须是数字（1-10）")
        return
    
    # 获取水族箱中该稀有度的所有鱼
    aquarium_result = self.aquarium_service.get_user_aquarium(user_id)
    if not aquarium_result.get("success"):
        yield event.plain_result(f"❌ 获取水族箱信息失败")
        return
    
    fishes = aquarium_result.get("fishes", [])
    target_fishes = [f for f in fishes if f.get("rarity") == rarity]
    
    if not target_fishes:
        yield event.plain_result(f"❌ 水族箱中没有{rarity}星稀有度的鱼")
        return
    
    # 批量移回鱼塘
    total_moved = 0
    high_quality_count = 0
    success_count = 0
    failed_items = []
    
    for fish in target_fishes:
        fish_id = fish.get("fish_id")
        quantity = fish.get("quantity", 0)
        quality_level = fish.get("quality_level", 0)
        
        if quantity > 0:
            result = self.aquarium_service.remove_fish_from_aquarium(user_id, fish_id, quantity, quality_level)
            if result.get("success"):
                total_moved += quantity
                if quality_level == 1:
                    high_quality_count += quantity
                success_count += 1
            else:
                failed_items.append(f"{fish.get('name')}({result.get('message')})")
    
    # 构建结果消息
    message = f"✅ 成功将 {success_count} 种{rarity}星鱼（共{total_moved}条）移回鱼塘"
    if high_quality_count > 0:
        message += f"\n✨ 其中包含 {high_quality_count} 条高品质鱼"
    if failed_items:
        message += f"\n\n⚠️ 以下鱼类移动失败：\n" + "\n".join(f"  - {item}" for item in failed_items[:5])
        if len(failed_items) > 5:
            message += f"\n  ... 还有{len(failed_items)-5}项"
    
    yield event.plain_result(message)