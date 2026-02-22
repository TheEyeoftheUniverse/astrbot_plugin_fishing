import functools
import os
from typing import Dict, Any
from datetime import datetime, timedelta
import json

from quart import (
    Quart, render_template, request, redirect, url_for, session, flash,
    Blueprint, current_app, jsonify
)
from astrbot.api import logger


player_bp = Blueprint(
    "player_bp",
    __name__,
    template_folder="templates",
    static_folder="static",
)

# 用户凭证持久化辅助函数
def _get_credentials_file():
    """获取凭证文件路径"""
    data_dir = os.path.join(os.path.dirname(os.path.dirname(__file__)), "data")
    os.makedirs(data_dir, exist_ok=True)
    return os.path.join(data_dir, "user_credentials.json")

def _load_credentials():
    """从文件加载用户凭证"""
    credentials_file = _get_credentials_file()
    if os.path.exists(credentials_file):
        try:
            with open(credentials_file, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception as e:
            logger.error(f"加载用户凭证失败: {e}")
            return {}
    return {}

def _save_credentials(credentials):
    """保存用户凭证到文件"""
    credentials_file = _get_credentials_file()
    try:
        with open(credentials_file, "w", encoding="utf-8") as f:
            json.dump(credentials, f, ensure_ascii=False, indent=2)
    except Exception as e:
        logger.error(f"保存用户凭证失败: {e}")

# 在启动时加载凭证
USER_CREDENTIALS = _load_credentials()

def _get_user_title(current_title_id, item_template_repo):
    """获取用户称号名称"""
    if not current_title_id:
        return "无称号"
    
    # 尝试从模板仓储获取称号
    if hasattr(item_template_repo, 'get_title_by_id'):
        title_info = item_template_repo.get_title_by_id(current_title_id)
        if title_info:
            return title_info.name
    
    # 简单映射
    title_names = {
        1: "新手渔夫",
        2: "钓鱾爱好者",
        3: "渔业专家",
        4: "传奇渔夫"
    }
    return title_names.get(current_title_id, f"称号#{current_title_id}")

def _get_leaderboard_data(user_repo, item_template_repo, top_n=10):
    """获取排行榜数据，包含用户称号显示"""
    try:
        # 获取所有用户
        all_users = user_repo.get_all_users()

        def _build_rank_list(users, key_fn, extra_field_name=None):
            ranking = sorted(users, key=key_fn, reverse=True)[:top_n]
            result = []
            for idx, u in enumerate(ranking):
                title = _get_user_title(getattr(u, 'current_title_id', None), item_template_repo)
                entry = {
                    "rank": idx + 1,
                    "user_id": u.user_id,
                    "nickname": u.nickname,
                    "current_title_id": getattr(u, 'current_title_id', None),
                    "title": title
                }
                if extra_field_name:
                    entry[extra_field_name] = getattr(u, extra_field_name, 0)
                result.append(entry)
            return result

        coins_leaderboard = _build_rank_list(all_users, lambda u: u.coins, 'coins')
        fishing_leaderboard = _build_rank_list(all_users, lambda u: u.total_fishing_count, 'total_fishing_count')
        weight_leaderboard = _build_rank_list(all_users, lambda u: u.total_weight_caught, 'total_weight_caught')
        earned_leaderboard = _build_rank_list(all_users, lambda u: u.total_coins_earned, 'total_coins_earned')

        return {
            "coins": coins_leaderboard,
            "fishing": fishing_leaderboard,
            "weight": weight_leaderboard,
            "earned": earned_leaderboard
        }
    except Exception as e:
        logger.error(f"获取排行榜数据失败: {e}")
        return {
            "coins": [],
            "fishing": [],
            "weight": [],
            "earned": []
        }

def _get_or_create_daily_exhibition(exhibition_file, user_repo, aquarium_service, inventory_repo, item_template_repo):
    """获取或创建今日展览数据"""
    from datetime import datetime, date
    import random
    
    today = date.today().isoformat()
    
    # 读取展览数据
    if os.path.exists(exhibition_file):
        with open(exhibition_file, "r", encoding="utf-8") as f:
            exhibition_data = json.load(f)
    else:
        exhibition_data = {"date": "", "featured_user": None, "comments": {}}

    # 如果文件中已经有今日的展览数据，确保其中的鱼类条目包含 description/min_weight/max_weight/actual_value 等字段。
    if exhibition_data.get("featured_user") and exhibition_data.get("date"):
        try:
            featured = exhibition_data.get("featured_user")
            fishes = featured.get("aquarium", []) if isinstance(featured.get("aquarium", []), list) else []
            for idx, fish in enumerate(fishes):
                if not isinstance(fish, dict):
                    continue
                # 如果缺少描述或重量信息，从模板仓储补充
                try:
                    fish_template = item_template_repo.get_fish_by_id(fish.get("fish_id"))
                except Exception:
                    fish_template = None

                if fish_template:
                    if not fish.get("description"):
                        fish["description"] = fish_template.description or "暂无描述"
                    if not fish.get("min_weight") and hasattr(fish_template, 'min_weight'):
                        fish["min_weight"] = fish_template.min_weight
                    if not fish.get("max_weight") and hasattr(fish_template, 'max_weight'):
                        fish["max_weight"] = fish_template.max_weight
                    if not fish.get("actual_value"):
                        fish["actual_value"] = fish_template.base_value * (1 + fish.get("quality_level", 0))

            # 将补充后的数据写回内存对象（不强制覆盖文件）
            exhibition_data["featured_user"]["aquarium"] = fishes
        except Exception:
            # 在补充展览数据时忽略错误，避免影响页面渲染
            pass
    
    # 检查是否需要更新展览
    if exhibition_data.get("date") != today:
        # 随机选择一个有水族箱内容的用户
        all_users = user_repo.get_all_users()
        eligible_users = []
        
        for user in all_users:
            aquarium_result = aquarium_service.get_user_aquarium(user.user_id)
            if aquarium_result.get("fishes") and len(aquarium_result["fishes"]) > 0:
                eligible_users.append(user)
        
        if eligible_users:
            featured_user = random.choice(eligible_users)
            
            # 获取用户装备信息
            equipped_rod = None
            rod_instance = inventory_repo.get_user_equipped_rod(featured_user.user_id)
            if rod_instance:
                rod_template = item_template_repo.get_rod_by_id(rod_instance.rod_id)
                if rod_template:
                    equipped_rod = {
                        "name": rod_template.name,
                        "rarity": rod_template.rarity,
                        "refine_level": rod_instance.refine_level
                    }
            
            equipped_accessory = None
            acc_instance = inventory_repo.get_user_equipped_accessory(featured_user.user_id)
            if acc_instance:
                acc_template = item_template_repo.get_accessory_by_id(acc_instance.accessory_id)
                if acc_template:
                    equipped_accessory = {
                        "name": acc_template.name,
                        "rarity": acc_template.rarity,
                        "refine_level": acc_instance.refine_level
                    }
            
            current_bait = None
            if featured_user.current_bait_id:
                bait_template = item_template_repo.get_bait_by_id(featured_user.current_bait_id)
                if bait_template:
                    bait_inventory = inventory_repo.get_user_bait_inventory(featured_user.user_id)
                    current_bait = {
                        "name": bait_template.name,
                        "rarity": bait_template.rarity,
                        "quantity": bait_inventory.get(featured_user.current_bait_id, 0)
                    }
            
            # 获取用户称号
            current_title = "无称号"
            if featured_user.current_title_id:
                # 尝试从模板仓储获取称号
                if hasattr(item_template_repo, 'get_title_by_id'):
                    title_info = item_template_repo.get_title_by_id(featured_user.current_title_id)
                    if title_info:
                        current_title = title_info.name
                    else:
                        current_title = f"称号#{featured_user.current_title_id}"
                else:
                    # 简单映射
                    title_names = {
                        1: "新手渔夫",
                        2: "钓鱼爱好者",
                        3: "渔业专家",
                        4: "传奇渔夫"
                    }
                    current_title = title_names.get(featured_user.current_title_id, f"称号#{featured_user.current_title_id}")
            
            # 获取水族箱内容
            aquarium_result = aquarium_service.get_user_aquarium(featured_user.user_id)
            
            # 为每条鱼添加完整的模板信息（参考pokedex图鉴页格式）
            enhanced_fishes = []
            for fish in aquarium_result.get("fishes", []):
                # aquarium_service已经返回了enriched的数据，直接使用
                enhanced_fish = fish.copy()
                
                # 获取完整的鱼类模板信息
                fish_template = item_template_repo.get_fish_by_id(fish["fish_id"])
                if fish_template:
                    # 确保有actual_value
                    if 'actual_value' not in enhanced_fish:
                        enhanced_fish["actual_value"] = fish_template.base_value * (1 + fish.get("quality_level", 0))
                    
                    # 描述信息
                    enhanced_fish["description"] = fish_template.description or "一条神秘的鱼"
                    enhanced_fish["base_value"] = fish_template.base_value
                    
                    # 重量信息（参考图鉴页格式，使用min_weight和max_weight）
                    if hasattr(fish_template, 'min_weight') and fish_template.min_weight:
                        enhanced_fish["min_weight"] = fish_template.min_weight
                    if hasattr(fish_template, 'max_weight') and fish_template.max_weight:
                        enhanced_fish["max_weight"] = fish_template.max_weight
                        
                enhanced_fishes.append(enhanced_fish)
            
            exhibition_data = {
                "date": today,
                "featured_user": {
                    "user_id": featured_user.user_id,
                    "nickname": featured_user.nickname or f"渔夫{featured_user.user_id[-4:]}",
                    "current_title": current_title,
                    "equipped_rod": equipped_rod,
                    "equipped_accessory": equipped_accessory,
                    "current_bait": current_bait,
                    "aquarium": enhanced_fishes,
                    "stats": aquarium_result.get("stats", {})
                },
                "comments": {}  # 新的一天清空留言
            }
            
            # 保存展览数据
            with open(exhibition_file, "w", encoding="utf-8") as f:
                json.dump(exhibition_data, f, ensure_ascii=False, indent=2)
        else:
            exhibition_data = {"date": today, "featured_user": None, "comments": {}}
    
    return exhibition_data

def create_player_app(services: Dict[str, Any]):
    """
    创建并配置玩家WebUI的Quart应用实例。

    Args:
        services: 包含所有需要注入的服务实例的字典。
    """
    app = Quart(__name__)
    app.secret_key = os.urandom(24)

    # 将服务实例存入app配置
    for service_name, service_instance in services.items():
        app.config[service_name.upper()] = service_instance

    app.register_blueprint(player_bp, url_prefix="/player")

    @app.route("/")
    def root():
        return redirect(url_for("player_bp.index"))
    
    @app.route("/favicon.ico")
    def favicon():
        from quart import abort
        abort(404)
    
    @app.errorhandler(404)
    async def handle_404_error(error):
        if not request.path.startswith('/player/static/') and request.path != '/favicon.ico':
            logger.error(f"404 Not Found: {request.url} - {request.method}")
        return "Not Found", 404
    
    @app.errorhandler(500)
    async def handle_500_error(error):
        logger.error(f"Internal Server Error: {error}")
        import traceback
        logger.error(traceback.format_exc())
        return "Internal Server Error", 500
    
    return app

def login_required(f):
    """装饰器：要求用户已登录"""
    @functools.wraps(f)
    async def decorated_function(*args, **kwargs):
        if "user_id" not in session:
            return redirect(url_for("player_bp.login"))
        return await f(*args, **kwargs)
    return decorated_function

# ==================== 认证路由 ====================

@player_bp.route("/login", methods=["GET", "POST"])
async def login():
    """用户登录页面"""
    if request.method == "POST":
        form = await request.form
        user_id = form.get("user_id", "").strip()
        password = form.get("password", "").strip()

        if not user_id:
            await flash("请输入用户ID", "danger")
            return await render_template("login.html")

        # 检查用户是否存在
        user_repo = current_app.config.get("USER_REPO")
        user = user_repo.get_by_id(user_id)
        
        if not user:
            await flash("🎣 你不是我们的钓鱼佬，去别处钓鱼吧！", "warning")
            logger.warning(f"未注册用户 {user_id} 尝试登录")
            return await render_template("login.html")

        # 检查是否首次登录（需要设置密钥）
        if user_id not in USER_CREDENTIALS:
            if not password:
                await flash("首次登录，请设置登录密钥", "warning")
                return await render_template("login.html", first_login=True, user_id=user_id)
            
            # 设置新密钥并保存
            USER_CREDENTIALS[user_id] = password
            _save_credentials(USER_CREDENTIALS)
            session["user_id"] = user_id
            session["nickname"] = user.nickname or user_id
            await flash(f"欢迎，{user.nickname or user_id}！密钥已设置", "success")
            logger.info(f"用户 {user_id} 首次登录并设置密钥")
            return redirect(url_for("player_bp.index"))
        
        # 验证密钥
        if USER_CREDENTIALS.get(user_id) != password:
            await flash("密钥错误", "danger")
            return await render_template("login.html")
        
        # 登录成功
        session["user_id"] = user_id
        session["nickname"] = user.nickname or user_id
        await flash(f"欢迎回来，{user.nickname or user_id}！", "success")
        logger.info(f"用户 {user_id} 登录成功")
        return redirect(url_for("player_bp.index"))
    
    # GET请求，显示登录页面
    return await render_template("login.html")

# ==================== API路由 ====================

@player_bp.route("/api/toggle_auto_fishing", methods=["POST"])
@login_required
async def toggle_auto_fishing():
    """切换自动钓鱼状态"""
    user_id = session.get("user_id")
    user_repo = current_app.config.get("USER_REPO")
    
    user = user_repo.get_by_id(user_id)
    if not user:
        return jsonify({"success": False, "message": "用户不存在"}), 404
    
    # 切换状态
    new_state = not user.auto_fishing_enabled
    user.auto_fishing_enabled = new_state
    user_repo.update(user)
    
    return jsonify({
        "success": True,
        "auto_fishing_enabled": new_state,
        "message": f"自动钓鱼已{'开启' if new_state else '关闭'}"
    })

@player_bp.route("/api/change_zone", methods=["POST"])
@login_required
async def change_zone():
    """切换钓鱼区域"""
    user_id = session.get("user_id")
    form = await request.form
    zone_id = form.get("zone_id")
    
    if not zone_id:
        return jsonify({"success": False, "message": "未指定区域"}), 400
    
    try:
        zone_id = int(zone_id)
    except ValueError:
        return jsonify({"success": False, "message": "无效的区域ID"}), 400
    
    fishing_service = current_app.config.get("FISHING_SERVICE")
    if not fishing_service:
        return jsonify({"success": False, "message": "服务不可用"}), 500
    
    # 调用fishing_service切换区域
    result = fishing_service.set_user_fishing_zone(user_id, zone_id)
    
    if result.get("success"):
        return jsonify({
            "success": True,
            "message": result.get("message", "切换成功")
        })
    else:
        return jsonify({
            "success": False,
            "message": result.get("message", "切换失败")
        }), 400

@player_bp.route("/api/sell_fish", methods=["POST"])
@login_required
async def api_sell_fish():
    """出售鱼类API"""
    user_id = session.get("user_id")
    inventory_service = current_app.config.get("INVENTORY_SERVICE")
    
    try:
        data = await request.get_json()
        fish_id = data.get("fish_id")
        quality_level = data.get("quality_level", 0)
        quantity = data.get("quantity", 1)
        
        if not fish_id or quantity <= 0:
            return jsonify({"success": False, "message": "参数无效"}), 400
        
        result = inventory_service.sell_fish(user_id, fish_id, quantity, quality_level)
        return jsonify(result)
    except Exception as e:
        logger.error(f"出售鱼类失败: {e}")
        return jsonify({"success": False, "message": str(e)}), 500

@player_bp.route("/api/daily_checkin", methods=["POST"])
@login_required
async def api_daily_checkin():
    """每日签到API"""
    user_id = session.get("user_id")
    user_service = current_app.config.get("USER_SERVICE")
    
    try:
        result = user_service.daily_sign_in(user_id)
        return jsonify(result)
    except Exception as e:
        logger.error(f"签到失败: {e}")
        return jsonify({"success": False, "message": str(e)}), 500
        return jsonify({"success": False, "message": str(e)}), 500

@player_bp.route("/api/sell_all_fish", methods=["POST"])
@login_required
async def api_sell_all_fish():
    """全部卖出鱼类API"""
    user_id = session.get("user_id")
    inventory_service = current_app.config.get("INVENTORY_SERVICE")
    
    try:
        data = await request.get_json()
        keep_one = data.get("keep_one", False)
        
        result = inventory_service.sell_all_fish(user_id, keep_one)
        return jsonify(result)
    except Exception as e:
        logger.error(f"全部卖出鱼类失败: {e}")
        return jsonify({"success": False, "message": str(e)}), 500

@player_bp.route("/api/add_to_aquarium", methods=["POST"])
@login_required
async def api_add_to_aquarium():
    """添加鱼到水族箱API"""
    user_id = session.get("user_id")
    aquarium_service = current_app.config.get("AQUARIUM_SERVICE")
    
    try:
        data = await request.get_json()
        fish_id = data.get("fish_id")
        quality_level = data.get("quality_level", 0)
        quantity = data.get("quantity", 1)
        
        if not fish_id or quantity <= 0:
            return jsonify({"success": False, "message": "参数无效"}), 400
        
        result = aquarium_service.add_fish_to_aquarium(user_id, fish_id, quantity, quality_level)
        return jsonify(result)
    except Exception as e:
        logger.error(f"添加到水族箱失败: {e}")
        return jsonify({"success": False, "message": str(e)}), 500

@player_bp.route("/api/buy_shop_item", methods=["POST"])
@login_required
async def api_buy_shop_item():
    """购买商店商品API"""
    user_id = session.get("user_id")
    shop_service = current_app.config.get("SHOP_SERVICE")
    
    try:
        data = await request.get_json()
        item_id = data.get("item_id")
        quantity = data.get("quantity", 1)
        
        if not item_id or quantity <= 0:
            return jsonify({"success": False, "message": "参数无效"}), 400
        
        result = shop_service.purchase_item(user_id, item_id, quantity)
        return jsonify(result)
    except Exception as e:
        logger.error(f"购买商店商品失败: {e}")
        return jsonify({"success": False, "message": str(e)}), 500

@player_bp.route("/api/list_item", methods=["POST"])
@login_required
async def api_list_item():
    """上架物品到市场API"""
    user_id = session.get("user_id")
    market_service = current_app.config.get("MARKET_SERVICE")
    
    try:
        data = await request.get_json()
        item_type = data.get("item_type")
        item_instance_id = data.get("item_instance_id")
        price = data.get("price")
        is_anonymous = data.get("is_anonymous", False)
        quantity = data.get("quantity", 1)
        quality_level = data.get("quality_level", 0)
        
        if not item_type or not item_instance_id or not price:
            return jsonify({"success": False, "message": "参数无效"}), 400
        
        result = market_service.put_item_on_sale(
            user_id, item_type, item_instance_id, price, 
            is_anonymous, quantity, quality_level
        )
        return jsonify(result)
    except Exception as e:
        logger.error(f"上架物品失败: {e}")
        return jsonify({"success": False, "message": str(e)}), 500

@player_bp.route("/api/buy_market_item", methods=["POST"])
@login_required
async def api_buy_market_item():
    """购买市场商品API"""
    user_id = session.get("user_id")
    market_service = current_app.config.get("MARKET_SERVICE")
    
    try:
        data = await request.get_json()
        market_id = data.get("market_id")
        
        if not market_id:
            return jsonify({"success": False, "message": "参数无效"}), 400
        
        result = market_service.buy_market_item(user_id, market_id)
        return jsonify(result)
    except Exception as e:
        logger.error(f"购买市场商品失败: {e}")
        return jsonify({"success": False, "message": str(e)}), 500

@player_bp.route("/api/delist_item", methods=["POST"])
@login_required
async def api_delist_item():
    """下架市场商品API"""
    user_id = session.get("user_id")
    market_service = current_app.config.get("MARKET_SERVICE")
    
    try:
        data = await request.get_json()
        market_id = data.get("market_id")
        
        if not market_id:
            return jsonify({"success": False, "message": "参数无效"}), 400
        
        result = market_service.delist_item(user_id, market_id)
        return jsonify(result)
    except Exception as e:
        logger.error(f"下架物品失败: {e}")
        return jsonify({"success": False, "message": str(e)}), 500

@player_bp.route("/api/open_exchange_account", methods=["POST"])
@login_required
async def api_open_exchange_account():
    """开通交易所账户API"""
    user_id = session.get("user_id")
    exchange_service = current_app.config.get("EXCHANGE_SERVICE")
    
    try:
        result = exchange_service.open_exchange_account(user_id)
        return jsonify(result)
    except Exception as e:
        logger.error(f"开通交易所账户失败: {e}")
        return jsonify({"success": False, "message": str(e)}), 500

@player_bp.route("/api/buy_commodity", methods=["POST"])
@login_required
async def api_buy_commodity():
    """购买大宗商品API"""
    user_id = session.get("user_id")
    exchange_service = current_app.config.get("EXCHANGE_SERVICE")
    
    try:
        data = await request.get_json()
        commodity_id = data.get("commodity_id")
        quantity = data.get("quantity")
        current_price = data.get("current_price")
        
        if not commodity_id or not quantity or not current_price:
            return jsonify({"success": False, "message": "参数无效"}), 400
        
        result = exchange_service.purchase_commodity(user_id, commodity_id, quantity, current_price)
        return jsonify(result)
    except Exception as e:
        logger.error(f"购买商品失败: {e}")
        return jsonify({"success": False, "message": str(e)}), 500

@player_bp.route("/api/sell_commodity", methods=["POST"])
@login_required
async def api_sell_commodity():
    """卖出大宗商品API"""
    user_id = session.get("user_id")
    exchange_service = current_app.config.get("EXCHANGE_SERVICE")
    
    try:
        data = await request.get_json()
        commodity_id = data.get("commodity_id")
        quantity = data.get("quantity")
        current_price = data.get("current_price")
        
        if not commodity_id or not quantity or not current_price:
            return jsonify({"success": False, "message": "参数无效"}), 400
        
        result = exchange_service.sell_commodity(user_id, commodity_id, quantity, current_price)
        return jsonify(result)
    except Exception as e:
        logger.error(f"卖出商品失败: {e}")
        return jsonify({"success": False, "message": str(e)}), 500

@player_bp.route("/api/remove_from_aquarium", methods=["POST"])
@login_required
async def api_remove_from_aquarium():
    """从水族箱移除鱼API"""
    user_id = session.get("user_id")
    aquarium_service = current_app.config.get("AQUARIUM_SERVICE")
    
    try:
        data = await request.get_json()
        fish_id = data.get("fish_id")
        quality_level = data.get("quality_level", 0)
        quantity = data.get("quantity", 1)
        
        if not fish_id or quantity <= 0:
            return jsonify({"success": False, "message": "参数无效"}), 400
        
        result = aquarium_service.remove_fish_from_aquarium(user_id, fish_id, quantity, quality_level)
        return jsonify(result)
    except Exception as e:
        logger.error(f"从水族箱移除失败: {e}")
        return jsonify({"success": False, "message": str(e)}), 500

@player_bp.route("/api/batch_move_to_aquarium", methods=["POST"])
@login_required
async def api_batch_move_to_aquarium():
    """批量按稀有度放入水族箱API"""
    user_id = session.get("user_id")
    aquarium_service = current_app.config.get("AQUARIUM_SERVICE")
    inventory_service = current_app.config.get("INVENTORY_SERVICE")
    
    try:
        data = await request.get_json()
        rarities = data.get("rarities", [])
        
        if not rarities or not isinstance(rarities, list):
            return jsonify({"success": False, "message": "参数无效"}), 400
        
        # 获取鱼塘信息
        inventory_result = inventory_service.get_user_fish_pond(user_id)
        if not inventory_result.get("success"):
            return jsonify({"success": False, "message": "获取鱼塘信息失败"}), 500
        
        fishes = inventory_result.get("fishes", [])
        total_moved = 0
        high_quality_count = 0
        success_count = 0
        failed_items = []
        
        # 对每个选中的稀有度进行处理
        for rarity in rarities:
            target_fishes = [f for f in fishes if f.get("rarity") == rarity]
            
            for fish in target_fishes:
                fish_id = fish.get("fish_id")
                quantity = fish.get("quantity", 0)
                quality_level = fish.get("quality_level", 0)
                
                if quantity > 0:
                    result = aquarium_service.add_fish_to_aquarium(user_id, fish_id, quantity, quality_level)
                    if result.get("success"):
                        total_moved += quantity
                        if quality_level == 1:
                            high_quality_count += quantity
                        success_count += 1
                    else:
                        failed_items.append(f"{fish.get('name')}({result.get('message')})")
        
        # 构建结果消息
        if total_moved == 0:
            return jsonify({"success": False, "message": "没有可移动的鱼"})
        
        message = f"✅ 成功将 {success_count} 种鱼（共{total_moved}条）放入水族箱"
        if high_quality_count > 0:
            message += f"\n✨ 其中包含 {high_quality_count} 条高品质鱼"
        if failed_items:
            message += f"\n\n⚠️ 部分鱼类移动失败：" + "、".join(failed_items[:3])
            if len(failed_items) > 3:
                message += f" 等{len(failed_items)}项"
        
        return jsonify({"success": True, "message": message})
    except Exception as e:
        logger.error(f"批量放入水族箱失败: {e}")
        return jsonify({"success": False, "message": str(e)}), 500

@player_bp.route("/api/batch_remove_from_aquarium", methods=["POST"])
@login_required
async def api_batch_remove_from_aquarium():
    """批量按稀有度移回鱼塘API"""
    user_id = session.get("user_id")
    aquarium_service = current_app.config.get("AQUARIUM_SERVICE")
    
    try:
        data = await request.get_json()
        rarities = data.get("rarities", [])
        
        if not rarities or not isinstance(rarities, list):
            return jsonify({"success": False, "message": "参数无效"}), 400
        
        # 获取水族箱信息
        aquarium_result = aquarium_service.get_user_aquarium(user_id)
        if not aquarium_result.get("success"):
            return jsonify({"success": False, "message": "获取水族箱信息失败"}), 500
        
        fishes = aquarium_result.get("fishes", [])
        total_moved = 0
        high_quality_count = 0
        success_count = 0
        failed_items = []
        
        # 对每个选中的稀有度进行处理
        for rarity in rarities:
            target_fishes = [f for f in fishes if f.get("rarity") == rarity]
            
            for fish in target_fishes:
                fish_id = fish.get("fish_id")
                quantity = fish.get("quantity", 0)
                quality_level = fish.get("quality_level", 0)
                
                if quantity > 0:
                    result = aquarium_service.remove_fish_from_aquarium(user_id, fish_id, quantity, quality_level)
                    if result.get("success"):
                        total_moved += quantity
                        if quality_level == 1:
                            high_quality_count += quantity
                        success_count += 1
                    else:
                        failed_items.append(f"{fish.get('name')}({result.get('message')})")
        
        # 构建结果消息
        if total_moved == 0:
            return jsonify({"success": False, "message": "没有可移动的鱼"})
        
        message = f"✅ 成功将 {success_count} 种鱼（共{total_moved}条）移回鱼塘"
        if high_quality_count > 0:
            message += f"\n✨ 其中包含 {high_quality_count} 条高品质鱼"
        if failed_items:
            message += f"\n\n⚠️ 部分鱼类移动失败：" + "、".join(failed_items[:3])
            if len(failed_items) > 3:
                message += f" 等{len(failed_items)}项"
        
        return jsonify({"success": True, "message": message})
    except Exception as e:
        logger.error(f"批量移回鱼塘失败: {e}")
        return jsonify({"success": False, "message": str(e)}), 500

@player_bp.route("/api/equip_rod", methods=["POST"])
@login_required
async def api_equip_rod():
    """装备鱼竿API"""
    user_id = session.get("user_id")
    inventory_service = current_app.config.get("INVENTORY_SERVICE")
    
    try:
        data = await request.get_json()
        rod_code = data.get("rod_code")
        
        if not rod_code:
            return jsonify({"success": False, "message": "参数无效"}), 400
        
        # 解析短码为实例ID
        instance_id = inventory_service.resolve_rod_instance_id(user_id, rod_code)
        if not instance_id:
            return jsonify({"success": False, "message": "无效的鱼竿编号"}), 400
        
        result = inventory_service.equip_item(user_id, instance_id, "rod")
        return jsonify(result)
    except Exception as e:
        logger.error(f"装备鱼竿失败: {e}")
        return jsonify({"success": False, "message": str(e)}), 500

@player_bp.route("/api/equip_accessory", methods=["POST"])
@login_required
async def api_equip_accessory():
    """装备饰品API"""
    user_id = session.get("user_id")
    inventory_service = current_app.config.get("INVENTORY_SERVICE")
    
    try:
        data = await request.get_json()
        accessory_code = data.get("accessory_code")
        
        if not accessory_code:
            return jsonify({"success": False, "message": "参数无效"}), 400
        
        # 解析短码为实例ID
        instance_id = inventory_service.resolve_accessory_instance_id(user_id, accessory_code)
        if not instance_id:
            return jsonify({"success": False, "message": "无效的饰品编号"}), 400
        
        result = inventory_service.equip_item(user_id, instance_id, "accessory")
        return jsonify(result)
    except Exception as e:
        logger.error(f"装备饰品失败: {e}")
        return jsonify({"success": False, "message": str(e)}), 500

@player_bp.route("/api/refine_rod", methods=["POST"])
@login_required
async def api_refine_rod():
    """精炼鱼竿API"""
    user_id = session.get("user_id")
    inventory_service = current_app.config.get("INVENTORY_SERVICE")
    
    try:
        data = await request.get_json()
        rod_code = data.get("rod_code")
        
        if not rod_code:
            return jsonify({"success": False, "message": "参数无效"}), 400
        
        # 解析短码为实例ID
        instance_id = inventory_service.resolve_rod_instance_id(user_id, rod_code)
        if not instance_id:
            return jsonify({"success": False, "message": "无效的鱼竿编号"}), 400
        
        result = inventory_service.refine(user_id, instance_id, "rod")
        return jsonify(result)
    except Exception as e:
        logger.error(f"精炼鱼竿失败: {e}")
        return jsonify({"success": False, "message": str(e)}), 500

@player_bp.route("/api/refine_accessory", methods=["POST"])
@login_required
async def api_refine_accessory():
    """精炼饰品API"""
    user_id = session.get("user_id")
    inventory_service = current_app.config.get("INVENTORY_SERVICE")
    
    try:
        data = await request.get_json()
        accessory_code = data.get("accessory_code")
        
        if not accessory_code:
            return jsonify({"success": False, "message": "参数无效"}), 400
        
        # 解析短码为实例ID
        instance_id = inventory_service.resolve_accessory_instance_id(user_id, accessory_code)
        if not instance_id:
            return jsonify({"success": False, "message": "无效的饰品编号"}), 400
        
        result = inventory_service.refine(user_id, instance_id, "accessory")
        return jsonify(result)
    except Exception as e:
        logger.error(f"精炼饰品失败: {e}")
        return jsonify({"success": False, "message": str(e)}), 500

@player_bp.route("/api/use_item", methods=["POST"])
@login_required
async def api_use_item():
    """使用道具API"""
    user_id = session.get("user_id")
    inventory_service = current_app.config.get("INVENTORY_SERVICE")
    
    try:
        data = await request.get_json()
        item_id = data.get("item_id")
        quantity = data.get("quantity", 1)
        
        if not item_id or quantity <= 0:
            return jsonify({"success": False, "message": "参数无效"}), 400
        
        result = inventory_service.use_item(user_id, item_id, quantity)
        return jsonify(result)
    except Exception as e:
        logger.error(f"使用道具失败: {e}")
        return jsonify({"success": False, "message": str(e)}), 500

@player_bp.route("/api/use_bait", methods=["POST"])
@login_required
async def api_use_bait():
    """使用鱼饵API"""
    user_id = session.get("user_id")
    inventory_service = current_app.config.get("INVENTORY_SERVICE")
    
    try:
        data = await request.get_json()
        bait_id = data.get("bait_id")
        
        if not bait_id:
            return jsonify({"success": False, "message": "参数无效"}), 400
        
        # use_bait方法只使用一个鱼饵并设置为当前使用的鱼饵
        result = inventory_service.use_bait(user_id, bait_id)
        return jsonify(result)
    except Exception as e:
        logger.error(f"使用鱼饵失败: {e}")
        return jsonify({"success": False, "message": str(e)}), 500

@player_bp.route("/api/get_pool_details")
@login_required
async def api_get_pool_details():
    """获取卡池详情API"""
    gacha_service = current_app.config.get("GACHA_SERVICE")
    
    try:
        pool_id = request.args.get("pool_id", type=int)
        if not pool_id:
            return jsonify({"success": False, "message": "参数无效"}), 400
        
        result = gacha_service.get_pool_details(pool_id)
        return jsonify(result)
    except Exception as e:
        logger.error(f"获取卡池详情失败: {e}")
        return jsonify({"success": False, "message": str(e)}), 500

@player_bp.route("/api/perform_draw", methods=["POST"])
@login_required
async def api_perform_draw():
    """执行抽卡API"""
    user_id = session.get("user_id")
    gacha_service = current_app.config.get("GACHA_SERVICE")
    
    try:
        data = await request.get_json()
        pool_id = data.get("pool_id")
        num_draws = data.get("num_draws", 1)
        
        if not pool_id or num_draws <= 0:
            return jsonify({"success": False, "message": "参数无效"}), 400
        
        result = gacha_service.perform_draw(user_id, pool_id, num_draws)
        return jsonify(result)
    except Exception as e:
        logger.error(f"抽卡失败: {e}")
        return jsonify({"success": False, "message": str(e)}), 500

@player_bp.route("/api/perform_multi_draw", methods=["POST"])
@login_required
async def api_perform_multi_draw():
    """执行多次十连抽卡API"""
    user_id = session.get("user_id")
    gacha_service = current_app.config.get("GACHA_SERVICE")
    
    try:
        data = await request.get_json()
        pool_id = data.get("pool_id")
        times = data.get("times", 1)
        
        if not pool_id or times <= 0 or times > 100:
            return jsonify({"success": False, "message": "参数无效，次数必须在1-100之间"}), 400
        
        # 获取卡池信息
        pool = gacha_service.gacha_repo.get_pool_by_id(pool_id)
        if not pool:
            return jsonify({"success": False, "message": "卡池不存在"}), 400
        
        # 计算总消耗
        use_premium_currency = (getattr(pool, "cost_premium_currency", 0) or 0) > 0
        total_draws = times * 10
        if use_premium_currency:
            total_cost = (pool.cost_premium_currency or 0) * total_draws
            cost_type = "高级货币"
        else:
            total_cost = (pool.cost_coins or 0) * total_draws
            cost_type = "金币"
        
        # 统计信息
        total_items = 0
        item_counts = {}
        rarity_counts = {i: 0 for i in range(1, 11)}
        coin_total = 0
        
        # 执行多次十连
        for i in range(times):
            result = gacha_service.perform_draw(user_id, pool_id, num_draws=10)
            if not result.get("success"):
                return jsonify({
                    "success": False,
                    "message": f"第{i+1}次十连失败: {result.get('message')}"
                })
            
            items = result.get("results", [])
            total_items += len(items)
            
            for item in items:
                if item.get("type") == "coins":
                    coin_total += item["quantity"]
                else:
                    item_name = item["name"]
                    rarity = item.get("rarity", 1)
                    
                    item_counts[item_name] = item_counts.get(item_name, 0) + 1
                    
                    if rarity <= 10:
                        rarity_counts[rarity] += 1
                    else:
                        rarity_counts[10] += 1
        
        return jsonify({
            "success": True,
            "times": times,
            "total_items": total_items,
            "total_cost": total_cost,
            "cost_type": cost_type,
            "rarity_counts": rarity_counts,
            "item_counts": item_counts,
            "coin_total": coin_total
        })
    except Exception as e:
        logger.error(f"多次十连失败: {e}")
        return jsonify({"success": False, "message": str(e)}), 500

@player_bp.route("/api/post_message", methods=["POST"])
@login_required
async def api_post_message():
    """发表留言API"""
    user_id = session.get("user_id")
    user_repo = current_app.config.get("USER_REPO")
    
    try:
        data = await request.get_json()
        content = data.get("content", "").strip()
        
        if not content:
            return jsonify({"success": False, "message": "留言内容不能为空"}), 400
        
        if len(content) > 500:
            return jsonify({"success": False, "message": "留言内容不能超过500字"}), 400
        
        # 获取用户信息
        user = user_repo.get_by_id(user_id)
        if not user:
            return jsonify({"success": False, "message": "用户不存在"}), 400
        
        # 读取留言数据
        data_dir = os.path.join(os.path.dirname(os.path.dirname(__file__)), "data")
        os.makedirs(data_dir, exist_ok=True)
        messages_file = os.path.join(data_dir, "tavern_messages.json")
        
        if os.path.exists(messages_file):
            with open(messages_file, "r", encoding="utf-8") as f:
                tavern_data = json.load(f)
        else:
            tavern_data = {"announcement": "", "messages": []}
        
        # 添加新留言
        import uuid
        new_message = {
            "id": str(uuid.uuid4()),
            "user_id": user_id,
            "username": user.nickname or f"渔夫{user_id[-4:]}",
            "content": content,
            "timestamp": datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        }
        
        # 插入到列表开头（最新的在前面）
        tavern_data.setdefault("messages", []).insert(0, new_message)
        
        # 限制最多保存1000条留言
        if len(tavern_data["messages"]) > 1000:
            tavern_data["messages"] = tavern_data["messages"][:1000]
        
        # 保存到文件
        with open(messages_file, "w", encoding="utf-8") as f:
            json.dump(tavern_data, f, ensure_ascii=False, indent=2)
        
        return jsonify({"success": True, "message": "留言发表成功！"})
    except Exception as e:
        logger.error(f"发表留言失败: {e}")
        return jsonify({"success": False, "message": str(e)}), 500

@player_bp.route("/api/delete_message", methods=["POST"])
@login_required
async def api_delete_message():
    """删除留言API"""
    user_id = session.get("user_id")
    ADMIN_ID = "2645956495"
    
    try:
        data = await request.get_json()
        message_id = data.get("message_id")
        
        if not message_id:
            return jsonify({"success": False, "message": "参数无效"}), 400
        
        # 读取留言数据
        data_dir = os.path.join(os.path.dirname(os.path.dirname(__file__)), "data")
        messages_file = os.path.join(data_dir, "tavern_messages.json")
        
        if not os.path.exists(messages_file):
            return jsonify({"success": False, "message": "留言不存在"}), 404
        
        with open(messages_file, "r", encoding="utf-8") as f:
            tavern_data = json.load(f)
        
        # 查找并删除留言
        messages = tavern_data.get("messages", [])
        message_to_delete = None
        
        for msg in messages:
            if msg.get("id") == message_id:
                message_to_delete = msg
                break
        
        if not message_to_delete:
            return jsonify({"success": False, "message": "留言不存在"}), 404
        
        # 检查权限（只能删除自己的留言或管理员可以删除所有）
        if message_to_delete.get("user_id") != user_id and user_id != ADMIN_ID:
            return jsonify({"success": False, "message": "无权删除此留言"}), 403
        
        # 删除留言
        tavern_data["messages"] = [msg for msg in messages if msg.get("id") != message_id]
        
        # 保存到文件
        with open(messages_file, "w", encoding="utf-8") as f:
            json.dump(tavern_data, f, ensure_ascii=False, indent=2)
        
        return jsonify({"success": True, "message": "留言已删除"})
    except Exception as e:
        logger.error(f"删除留言失败: {e}")
        return jsonify({"success": False, "message": str(e)}), 500

@player_bp.route("/api/update_announcement", methods=["POST"])
@login_required
async def api_update_announcement():
    """更新公告API（仅管理员）"""
    user_id = session.get("user_id")
    ADMIN_ID = "2645956495"
    
    if user_id != ADMIN_ID:
        return jsonify({"success": False, "message": "无权限操作"}), 403
    
    try:
        data = await request.get_json()
        content = data.get("content", "")
        
        # 读取留言数据
        data_dir = os.path.join(os.path.dirname(os.path.dirname(__file__)), "data")
        os.makedirs(data_dir, exist_ok=True)
        messages_file = os.path.join(data_dir, "tavern_messages.json")
        
        if os.path.exists(messages_file):
            with open(messages_file, "r", encoding="utf-8") as f:
                tavern_data = json.load(f)
        else:
            tavern_data = {"announcement": "", "messages": []}
        
        # 更新公告
        tavern_data["announcement"] = content
        
        # 保存到文件
        with open(messages_file, "w", encoding="utf-8") as f:
            json.dump(tavern_data, f, ensure_ascii=False, indent=2)
        
        return jsonify({"success": True, "message": "公告更新成功！"})
    except Exception as e:
        logger.error(f"更新公告失败: {e}")
        return jsonify({"success": False, "message": str(e)}), 500

@player_bp.route("/api/add_exhibition_comment", methods=["POST"])
@login_required
async def api_add_exhibition_comment():
    """添加展览鱼类评论API"""
    user_id = session.get("user_id")
    user_repo = current_app.config.get("USER_REPO")
    
    try:
        data = await request.get_json()
        fish_key = data.get("fish_key")  # "fish_id-quality_level" 格式
        content = data.get("content", "").strip()
        
        if not fish_key or not content:
            return jsonify({"success": False, "message": "参数无效"}), 400
        
        if len(content) > 200:
            return jsonify({"success": False, "message": "评论内容不能超过200字"}), 400
        
        # 获取用户信息
        user = user_repo.get_by_id(user_id)
        if not user:
            return jsonify({"success": False, "message": "用户不存在"}), 400
        
        # 读取展览数据
        data_dir = os.path.join(os.path.dirname(os.path.dirname(__file__)), "data")
        exhibition_file = os.path.join(data_dir, "aquarium_exhibition.json")
        
        if not os.path.exists(exhibition_file):
            return jsonify({"success": False, "message": "展览数据不存在"}), 404
        
        with open(exhibition_file, "r", encoding="utf-8") as f:
            exhibition_data = json.load(f)
        
        if not exhibition_data.get("featured_user"):
            return jsonify({"success": False, "message": "当前没有展览"}), 404
        
        # 添加评论
        import uuid
        if "comments" not in exhibition_data:
            exhibition_data["comments"] = {}
        
        if fish_key not in exhibition_data["comments"]:
            exhibition_data["comments"][fish_key] = []
        
        new_comment = {
            "id": str(uuid.uuid4()),
            "user_id": user_id,
            "username": user.nickname or f"渔夫{user_id[-4:]}",
            "content": content,
            "timestamp": datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        }
        
        exhibition_data["comments"][fish_key].append(new_comment)
        
        # 保存到文件
        with open(exhibition_file, "w", encoding="utf-8") as f:
            json.dump(exhibition_data, f, ensure_ascii=False, indent=2)
        
        return jsonify({"success": True, "message": "评论发表成功！"})
    except Exception as e:
        logger.error(f"添加展览评论失败: {e}")
        return jsonify({"success": False, "message": str(e)}), 500

@player_bp.route("/api/delete_exhibition_comment", methods=["POST"])
@login_required
async def api_delete_exhibition_comment():
    """删除展览评论API"""
    user_id = session.get("user_id")
    
    try:
        data = await request.get_json()
        fish_key = data.get("fish_key")
        comment_id = data.get("comment_id")
        
        if not fish_key or not comment_id:
            return jsonify({"success": False, "message": "参数无效"}), 400
        
        # 读取展览数据
        data_dir = os.path.join(os.path.dirname(os.path.dirname(__file__)), "data")
        exhibition_file = os.path.join(data_dir, "aquarium_exhibition.json")
        
        if not os.path.exists(exhibition_file):
            return jsonify({"success": False, "message": "展览数据不存在"}), 404
        
        with open(exhibition_file, "r", encoding="utf-8") as f:
            exhibition_data = json.load(f)
        
        # 检查评论是否存在
        if fish_key not in exhibition_data.get("comments", {}):
            return jsonify({"success": False, "message": "评论不存在"}), 404
        
        comments = exhibition_data["comments"][fish_key]
        comment_to_delete = None
        
        for comment in comments:
            if comment.get("id") == comment_id:
                comment_to_delete = comment
                break
        
        if not comment_to_delete:
            return jsonify({"success": False, "message": "评论不存在"}), 404
        
        # 检查权限（只能删除自己的评论或展览者可以删除所有评论）
        exhibition_owner_id = exhibition_data.get("featured_user", {}).get("user_id")
        if comment_to_delete.get("user_id") != user_id and user_id != exhibition_owner_id:
            return jsonify({"success": False, "message": "无权删除此评论"}), 403
        
        # 删除评论
        exhibition_data["comments"][fish_key] = [
            c for c in comments if c.get("id") != comment_id
        ]
        
        # 如果该鱼没有评论了，删除这个key
        if not exhibition_data["comments"][fish_key]:
            del exhibition_data["comments"][fish_key]
        
        # 保存到文件
        with open(exhibition_file, "w", encoding="utf-8") as f:
            json.dump(exhibition_data, f, ensure_ascii=False, indent=2)
        
        return jsonify({"success": True, "message": "评论已删除"})
    except Exception as e:
        logger.error(f"删除展览评论失败: {e}")
        return jsonify({"success": False, "message": str(e)}), 500

@player_bp.route("/logout")
async def logout():
    """用户登出"""
    user_id = session.get("user_id")
    session.clear()
    if user_id:
        logger.info(f"用户 {user_id} 登出")
    await flash("已成功登出", "info")
    return redirect(url_for("player_bp.login"))

# ==================== 主页面 ====================

@player_bp.route("/")
@player_bp.route("/index")
@login_required
async def index():
    """玩家主页 - 仪表板"""
    user_id = session.get("user_id")
    user_repo = current_app.config.get("USER_REPO")
    inventory_repo = current_app.config.get("INVENTORY_REPO")
    item_template_repo = current_app.config.get("ITEM_TEMPLATE_REPO")
    log_repo = current_app.config.get("LOG_REPO")
    buff_repo = current_app.config.get("BUFF_REPO")
    fishing_service = current_app.config.get("FISHING_SERVICE")
    
    user = user_repo.get_by_id(user_id)
    if not user:
        await flash("用户数据异常", "danger")
        return redirect(url_for("player_bp.logout"))
    
    # 使用与游戏中状态显示相同的数据获取函数
    from ..draw.state import get_user_state_data
    from ..core.utils import get_now
    
    game_config = current_app.config.get("FISHING_SERVICE").config if fishing_service else {}
    user_state = get_user_state_data(
        user_repo, inventory_repo, item_template_repo, 
        log_repo, buff_repo, game_config, user_id
    )
    
    if not user_state:
        await flash("无法获取用户状态", "danger")
        return redirect(url_for("player_bp.logout"))
    
    # 获取基本统计信息
    fish_inventory = inventory_repo.get_fish_inventory(user_id)
    fish_count = sum(item.quantity for item in fish_inventory)
    
    # 计算鱼塘总价值
    fish_pond_value = inventory_repo.get_fish_inventory_value(user_id)
    
    # 计算钓鱼CD剩余时间（考虑鱼饵星级）
    fishing_cooldown_remaining = 0
    if user.last_fishing_time:
        base_cooldown = game_config.get("fishing", {}).get("cooldown_seconds", 180)
        
        # 获取当前鱼饵的星级来计算CD减少
        cooldown_seconds = base_cooldown
        if user.current_bait_id:
            bait_template = item_template_repo.get_bait_by_id(user.current_bait_id)
            if bait_template and bait_template.rarity >= 5:
                # 5星开始，每星减少10%，上限60%（10星）
                reduction_percent = min((bait_template.rarity - 4) * 0.1, 0.6)
                cooldown_seconds = base_cooldown * (1.0 - reduction_percent)
        
        now = get_now()
        if user.last_fishing_time.tzinfo is None and now.tzinfo is not None:
            now = now.replace(tzinfo=None)
        elif user.last_fishing_time.tzinfo is not None and now.tzinfo is None:
            now = now.replace(tzinfo=user.last_fishing_time.tzinfo)
        
        elapsed = (now - user.last_fishing_time).total_seconds()
        if elapsed < cooldown_seconds:
            fishing_cooldown_remaining = int(cooldown_seconds - elapsed)
    
    user_state['fishing_cooldown_remaining'] = fishing_cooldown_remaining
    
    # 检查今日是否已签到
    from ..core.utils import get_today
    today = get_today()
    has_checked_in_today = log_repo.has_checked_in(user_id, today)
    
    stats = {
        "coins": user.coins,
        "premium_currency": user.premium_currency,
        "total_fishing_count": user.total_fishing_count,
        "fish_count": fish_count,
        "fish_pond_capacity": user.fish_pond_capacity,
        "fish_pond_value": fish_pond_value,
        "consecutive_login_days": user.consecutive_login_days,
        "has_checked_in_today": has_checked_in_today,
    }
    
    return await render_template("index.html", user=user, stats=stats, user_state=user_state)

# ==================== 功能页面（占位符） ====================

@player_bp.route("/profile")
@login_required
async def profile():
    """个人状态页面"""
    user_id = session.get("user_id")
    return await render_template("placeholder.html", 
                                  page_title="个人状态", 
                                  page_icon="fa-user",
                                  description="查看您的详细信息、装备、称号等")

@player_bp.route("/pokedex")
@login_required
async def pokedex():
    """鱼类图鉴页面"""
    user_id = session.get("user_id")
    item_template_repo = current_app.config.get("ITEM_TEMPLATE_REPO")
    log_repo = current_app.config.get("LOG_REPO")
    
    # 获取所有鱼类模板
    all_fish = item_template_repo.get_all_fish()
    
    # 从日志中获取用户历史钓到过的鱼类统计
    fish_stats = log_repo.get_user_fish_stats(user_id)
    
    # 创建已钓到的鱼类ID到统计数据的映射
    caught_fish_map = {}
    for stat in fish_stats:
        caught_fish_map[stat.fish_id] = {
            "total_caught": stat.total_caught,
            "max_weight": stat.max_weight,
            "min_weight": stat.min_weight,
            "first_caught_at": stat.first_caught_at,
            "last_caught_at": stat.last_caught_at
        }
    
    # 按稀有度分组
    fish_by_rarity = {}
    for fish in all_fish:
        rarity = fish.rarity
        if rarity not in fish_by_rarity:
            fish_by_rarity[rarity] = []
        
        is_caught = fish.fish_id in caught_fish_map
        fish_data = {
            "id": fish.fish_id,
            "name": fish.name,
            "rarity": fish.rarity,
            "base_value": fish.base_value,
            "description": fish.description,
            "is_caught": is_caught
        }
        
        # 如果已钓到，添加统计数据
        if is_caught:
            fish_data.update(caught_fish_map[fish.fish_id])
        
        fish_by_rarity[rarity].append(fish_data)
    
    # 排序
    for rarity in fish_by_rarity:
        fish_by_rarity[rarity].sort(key=lambda x: x["id"])
    
    return await render_template("pokedex.html", 
                                  fish_by_rarity=fish_by_rarity,
                                  total_fish=len(all_fish),
                                  caught_count=len(caught_fish_map))

@player_bp.route("/inventory")
@login_required
async def inventory():
    """背包页面"""
    user_id = session.get("user_id")
    inventory_service = current_app.config.get("INVENTORY_SERVICE")
    
    # 获取鱼竿、饰品、道具、鱼饵
    rods_result = inventory_service.get_user_rod_inventory(user_id)
    accessories_result = inventory_service.get_user_accessory_inventory(user_id)
    items_result = inventory_service.get_user_item_inventory(user_id)
    baits_result = inventory_service.get_user_bait_inventory(user_id)
    
    return await render_template("inventory.html",
                                  rods=rods_result.get("rods", []),
                                  accessories=accessories_result.get("accessories", []),
                                  items=items_result.get("items", []),
                                  baits=baits_result.get("baits", []))

@player_bp.route("/fishpond")
@login_required
async def fishpond():
    """鱼塘页面"""
    user_id = session.get("user_id")
    inventory_service = current_app.config.get("INVENTORY_SERVICE")
    
    # 获取鱼塘信息
    pond_result = inventory_service.get_user_fish_pond(user_id)
    
    # 按稀有度分组
    fish_by_rarity = {}
    for fish in pond_result.get("fishes", []):
        rarity = fish["rarity"]
        if rarity not in fish_by_rarity:
            fish_by_rarity[rarity] = []
        fish_by_rarity[rarity].append(fish)
    
    return await render_template("fishpond.html",
                                  fish_by_rarity=fish_by_rarity,
                                  stats=pond_result.get("stats", {}))

@player_bp.route("/aquarium")
@login_required
async def aquarium():
    """水族箱页面"""
    user_id = session.get("user_id")
    aquarium_service = current_app.config.get("AQUARIUM_SERVICE")
    
    # 获取水族箱信息
    aquarium_result = aquarium_service.get_user_aquarium(user_id)
    
    # 按稀有度分组
    fish_by_rarity = {}
    for fish in aquarium_result.get("fishes", []):
        rarity = fish["rarity"]
        if rarity not in fish_by_rarity:
            fish_by_rarity[rarity] = []
        fish_by_rarity[rarity].append(fish)
    
    # 读取展览评论数据（如果用户是展览者）
    exhibition_comments = {}
    data_dir = os.path.join(os.path.dirname(os.path.dirname(__file__)), "data")
    exhibition_file = os.path.join(data_dir, "aquarium_exhibition.json")
    
    if os.path.exists(exhibition_file):
        with open(exhibition_file, "r", encoding="utf-8") as f:
            exhibition_data = json.load(f)
        
        # 如果当前用户是展览者，获取评论
        if exhibition_data.get("featured_user", {}).get("user_id") == user_id:
            exhibition_comments = exhibition_data.get("comments", {})
    
    return await render_template("aquarium.html",
                                  fish_by_rarity=fish_by_rarity,
                                  stats=aquarium_result.get("stats", {}),
                                  exhibition_comments=exhibition_comments,
                                  current_user_id=user_id)

@player_bp.route("/market")
@login_required
async def market():
    """交易市场页面"""
    user_id = session.get("user_id")
    market_service = current_app.config.get("MARKET_SERVICE")
    inventory_service = current_app.config.get("INVENTORY_SERVICE")
    
    # 获取市场商品列表
    market_result = market_service.get_market_listings()
    
    # 获取用户的上架列表
    my_listings_result = market_service.get_user_listings(user_id)
    
    # 获取用户库存用于上架
    user_inventory = {
        "rod": [],
        "accessory": [],
        "fish": [],
        "item": []
    }
    
    # 获取鱼竿
    rods_result = inventory_service.get_user_rod_inventory(user_id)
    for rod in rods_result.get("rods", []):
        if not rod.get("is_equipped"):  # 只显示未装备的
            user_inventory["rod"].append({
                "instance_id": rod["instance_id"],
                "name": rod["name"],
                "rarity": rod["rarity"],
                "refine_level": rod.get("refine_level", 0),
                "display_code": rod.get("display_code", "")
            })
    
    # 获取饰品
    accessories_result = inventory_service.get_user_accessory_inventory(user_id)
    for accessory in accessories_result.get("accessories", []):
        if not accessory.get("is_equipped"):  # 只显示未装备的
            user_inventory["accessory"].append({
                "instance_id": accessory["instance_id"],
                "name": accessory["name"],
                "rarity": accessory["rarity"],
                "refine_level": accessory.get("refine_level", 0),
                "display_code": accessory.get("display_code", "")
            })
    
    # 获取鱼类（从鱼塘）
    pond_result = inventory_service.get_user_fish_pond(user_id)
    for fish in pond_result.get("fishes", []):
        user_inventory["fish"].append({
            "fish_id": fish["fish_id"],
            "name": fish["name"],
            "rarity": fish["rarity"],
            "quality_level": fish["quality_level"],
            "quantity": fish["quantity"]
        })
    
    # 获取道具
    items_result = inventory_service.get_user_item_inventory(user_id)
    for item in items_result.get("items", []):
        user_inventory["item"].append({
            "item_id": item["item_id"],
            "name": item["name"],
            "rarity": item["rarity"],
            "quantity": item["quantity"]
        })
    
    import json
    user_inventory_json = json.dumps(user_inventory)
    
    return await render_template("market.html",
                                  rods=market_result.get("rods", []),
                                  accessories=market_result.get("accessories", []),
                                  fish=market_result.get("fish", []),
                                  items=market_result.get("items", []),
                                  my_listings=my_listings_result.get("listings", []),
                                  user_inventory_json=user_inventory_json,
                                  user_id=user_id)

@player_bp.route("/shop")
@login_required
async def shop():
    """商店页面"""
    user_id = session.get("user_id")
    shop_service = current_app.config.get("SHOP_SERVICE")
    user_repo = current_app.config.get("USER_REPO")
    inventory_repo = current_app.config.get("INVENTORY_REPO")
    
    # 获取用户信息
    user = user_repo.get_by_id(user_id)
    
    # 获取用户库存用于检查购买条件
    user_inventory = {
        "coins": user.coins,
        "premium": user.premium_currency,
        "items": {},
        "fish": {},
        "rods": {},
        "accessories": {},
        "baits": {}
    }
    
    # 获取道具库存（inventory_repo返回的是字典 {item_id: quantity}）
    user_inventory["items"] = inventory_repo.get_user_item_inventory(user_id)
    
    # 获取鱼类库存（鱼塘 + 水族箱）
    for fish in inventory_repo.get_fish_inventory(user_id):
        key = (fish.fish_id, fish.quality_level)
        user_inventory["fish"][key] = user_inventory["fish"].get(key, 0) + fish.quantity
    
    from ..core.services.aquarium_service import AquariumService
    aquarium_service = current_app.config.get("AQUARIUM_SERVICE")
    if aquarium_service:
        aquarium_result = aquarium_service.get_user_aquarium(user_id)
        for fish in aquarium_result.get("fishes", []):
            key = (fish["fish_id"], fish["quality_level"])
            user_inventory["fish"][key] = user_inventory["fish"].get(key, 0) + fish["quantity"]
    
    # 获取鱼竿库存
    for rod in inventory_repo.get_user_rod_instances(user_id):
        user_inventory["rods"][rod.rod_id] = user_inventory["rods"].get(rod.rod_id, 0) + 1
    
    # 获取饰品库存
    for accessory in inventory_repo.get_user_accessory_instances(user_id):
        user_inventory["accessories"][accessory.accessory_id] = user_inventory["accessories"].get(accessory.accessory_id, 0) + 1
    
    # 获取鱼饵库存（inventory_repo返回的是字典 {bait_id: quantity}）
    user_inventory["baits"] = inventory_repo.get_user_bait_inventory(user_id)
    
    # 获取所有商店
    shops_result = shop_service.get_shops()
    shops_list = shops_result.get("shops", [])
    
    # 为每个商店获取详细信息
    shops_with_items = []
    for shop in shops_list:
        shop_details = shop_service.get_shop_details(shop["shop_id"])
        if shop_details.get("success"):
            # 为每个商品的成本检查是否满足
            for item_data in shop_details.get("items", []):
                for cost in item_data.get("costs", []):
                    cost_type = cost.get("cost_type")
                    cost_item_id = cost.get("cost_item_id")
                    cost_amount = cost.get("cost_amount", 0)
                    quality_level = cost.get("quality_level", 0)
                    
                    # 检查是否满足
                    satisfied = False
                    if cost_type == "coins":
                        satisfied = user_inventory["coins"] >= cost_amount
                    elif cost_type == "premium":
                        satisfied = user_inventory["premium"] >= cost_amount
                    elif cost_type == "item":
                        satisfied = user_inventory["items"].get(cost_item_id, 0) >= cost_amount
                    elif cost_type == "fish":
                        key = (cost_item_id, quality_level)
                        satisfied = user_inventory["fish"].get(key, 0) >= cost_amount
                    elif cost_type == "rod":
                        satisfied = user_inventory["rods"].get(cost_item_id, 0) >= cost_amount
                    elif cost_type == "accessory":
                        satisfied = user_inventory["accessories"].get(cost_item_id, 0) >= cost_amount
                    elif cost_type == "bait":
                        satisfied = user_inventory["baits"].get(cost_item_id, 0) >= cost_amount
                    
                    cost["satisfied"] = satisfied
            
            shops_with_items.append({
                "shop_id": shop["shop_id"],
                "name": shop["name"],
                "description": shop.get("description"),
                "item_list": shop_details.get("items", [])
            })
    
    return await render_template("shop.html", 
                                  user=user,
                                  shops=shops_with_items)

@player_bp.route("/exchange")
@login_required
async def exchange():
    """交易所页面"""
    user_id = session.get("user_id")
    exchange_service = current_app.config.get("EXCHANGE_SERVICE")
    user_repo = current_app.config.get("USER_REPO")
    
    # 检查是否开通账户
    account_check = exchange_service.check_exchange_account(user_id)
    has_account = account_check.get("success", False)
    
    # 获取用户信息用于显示金币
    user = user_repo.get_by_id(user_id)
    
    # 获取开户费用
    account_fee = exchange_service.config.get("account_fee", 100000)
    
    if not has_account:
        return await render_template("exchange.html",
                                      has_account=False,
                                      user=user,
                                      account_fee=account_fee,
                                      market_status={"commodities": []},
                                      user_inventory={},
                                      user_costs={},
                                      price_history={},
                                      history_data={},
                                      labels=[])
    
    # 获取市场状态
    market_status = exchange_service.get_market_status()
    
    # 获取用户库存
    user_inventory_result = exchange_service.get_user_inventory(user_id)
    inventory_data = user_inventory_result.get("inventory", {})
    
    # 构建用户库存字典和成本字典
    user_inventory = {}
    user_costs = {}
    for commodity_id, data in inventory_data.items():
        user_inventory[commodity_id] = data.get("total_quantity", 0)
        user_costs[commodity_id] = data.get("total_cost", 0)
    
    # 获取价格历史
    price_history_result = exchange_service.get_price_history(days=7)
    history_data = price_history_result.get("history", {})
    labels = price_history_result.get("labels", [])
    
    # 转换数据结构：从 {commodity_id: [prices]} 转换为 {date: {commodity_id: price}}
    price_history = {}
    for i, date in enumerate(labels):
        price_history[date] = {}
        for commodity_id, prices in history_data.items():
            if i < len(prices):
                price_history[date][commodity_id] = prices[i]
    
    return await render_template("exchange.html",
                                  has_account=True,
                                  user=user,
                                  account_fee=account_fee,
                                  market_status=market_status,
                                  user_inventory=user_inventory,
                                  user_costs=user_costs,
                                  price_history=price_history,
                                  history_data=history_data,
                                  labels=labels)

@player_bp.route("/gacha")
@login_required
async def gacha():
    """抽卡页面"""
    user_id = session.get("user_id")
    user_repo = current_app.config.get("USER_REPO")
    gacha_service = current_app.config.get("GACHA_SERVICE")
    log_repo = current_app.config.get("LOG_REPO")
    
    user = user_repo.get_by_id(user_id)
    if not user:
        await flash("用户数据异常", "danger")
        return redirect(url_for("player_bp.logout"))
    
    # 获取所有卡池
    pools_result = gacha_service.get_all_pools()
    all_pools_raw = pools_result.get("pools", [])
    
    # 获取免费卡池
    free_pool = gacha_service.get_daily_free_pool()
    free_pool_id = free_pool.gacha_pool_id if free_pool else None
    
    # 将卡池对象转换为字典并添加额外信息
    all_pools = []
    for pool in all_pools_raw:
        # 如果是字典直接用，否则转换为字典
        if isinstance(pool, dict):
            pool_dict = pool.copy()
        else:
            pool_dict = {
                "gacha_pool_id": pool.gacha_pool_id,
                "name": pool.name,
                "description": pool.description,
                "cost_coins": pool.cost_coins,
                "cost_premium_currency": pool.cost_premium_currency,
                "is_limited_time": bool(pool.is_limited_time),
                "open_until": pool.open_until
            }
        
        # 检查是否为免费卡池
        pool_dict["is_free"] = (free_pool_id and pool_dict["gacha_pool_id"] == free_pool_id)
        if pool_dict["is_free"]:
            # 检查今天是否已经抽过
            draws_today = log_repo.get_gacha_records_count_today(user_id, pool_dict["gacha_pool_id"])
            pool_dict["drawn_today"] = draws_today >= 1
        else:
            pool_dict["drawn_today"] = False
        
        all_pools.append(pool_dict)
    
    # 获取最近的抽卡记录
    recent_records = log_repo.get_gacha_records(user_id, limit=10)
    
    return await render_template("gacha.html",
                                  user=user,
                                  pools=all_pools,
                                  recent_records=recent_records)

@player_bp.route("/tavern")
@login_required
async def tavern():
    """酒馆页面"""
    user_id = session.get("user_id")
    user_repo = current_app.config.get("USER_REPO")
    aquarium_service = current_app.config.get("AQUARIUM_SERVICE")
    inventory_repo = current_app.config.get("INVENTORY_REPO")
    item_template_repo = current_app.config.get("ITEM_TEMPLATE_REPO")
    expedition_service = current_app.config.get("EXPEDITION_SERVICE")
    
    user = user_repo.get_by_id(user_id)
    if not user:
        await flash("用户数据异常", "danger")
        return redirect(url_for("player_bp.logout"))
    
    # 管理员ID
    ADMIN_ID = "2645956495"
    is_admin = (user_id == ADMIN_ID)
    
    # 获取留言数据文件路径
    data_dir = os.path.join(os.path.dirname(os.path.dirname(__file__)), "data")
    os.makedirs(data_dir, exist_ok=True)
    messages_file = os.path.join(data_dir, "tavern_messages.json")
    exhibition_file = os.path.join(data_dir, "aquarium_exhibition.json")
    
    # 读取留言数据
    if os.path.exists(messages_file):
        with open(messages_file, "r", encoding="utf-8") as f:
            tavern_data = json.load(f)
    else:
        tavern_data = {"announcement": "", "messages": []}
    
    # 分页
    page = request.args.get("page", 1, type=int)
    per_page = 20
    messages = tavern_data.get("messages", [])
    total_messages = len(messages)
    total_pages = (total_messages + per_page - 1) // per_page
    
    start_idx = (page - 1) * per_page
    end_idx = start_idx + per_page
    page_messages = messages[start_idx:end_idx]
    
    # 获取排行榜数据
    leaderboard = _get_leaderboard_data(user_repo, item_template_repo)
    
    # 获取今日展览数据
    exhibition_data = _get_or_create_daily_exhibition(
        exhibition_file, user_repo, aquarium_service, 
        inventory_repo, item_template_repo
    )
    
    # 获取进行中的科考
    active_expeditions = []
    if expedition_service:
        try:
            active_expeditions = expedition_service.get_all_active_expeditions()
            logger.info(f"成功获取科考数据，共{len(active_expeditions)}个进行中的科考")
            if active_expeditions:
                logger.info(f"科考数据示例: {active_expeditions[0]}")
        except Exception as e:
            logger.error(f"获取科考数据失败: {e}", exc_info=True)
    else:
        logger.warning("expedition_service未初始化")
    
    return await render_template("tavern.html",
                                  user=user,
                                  announcement=tavern_data.get("announcement", ""),
                                  messages=page_messages,
                                  is_admin=is_admin,
                                  current_user_id=user_id,
                                  page=page,
                                  total_pages=total_pages,
                                  leaderboard=leaderboard,
                                  exhibition=exhibition_data,
                                  expeditions=active_expeditions)

@player_bp.route("/fishing")
@login_required
async def fishing():
    """钓鱼区域管理页面"""
    user_id = session.get("user_id")
    user_repo = current_app.config.get("USER_REPO")
    fishing_service = current_app.config.get("FISHING_SERVICE")
    inventory_repo = current_app.config.get("INVENTORY_REPO")
    item_template_repo = current_app.config.get("ITEM_TEMPLATE_REPO")
    
    user = user_repo.get_by_id(user_id)
    if not user:
        await flash("用户数据异常", "danger")
        return redirect(url_for("player_bp.logout"))
    
    # 从数据库获取所有钓鱼区域
    fishing_zones = inventory_repo.get_all_zones()
    
    # 获取用户当前区域
    current_zone_id = user.fishing_zone_id
    current_zone = None
    
    # 构建所有区域列表
    all_zones = []
    for zone in fishing_zones:
        # 获取通行证道具名称
        required_pass_name = None
        if zone.requires_pass and zone.required_item_id:
            item_template = item_template_repo.get_item_by_id(zone.required_item_id)
            required_pass_name = item_template.name if item_template else f"道具ID{zone.required_item_id}"
        
        zone_info = {
            "id": zone.id,
            "name": zone.name,
            "description": zone.description,
            "required_pass": required_pass_name,
            "is_current": zone.id == current_zone_id,
            "is_active": zone.is_active,
            "fishing_cost": zone.fishing_cost,
        }
        
        all_zones.append(zone_info)
        
        # 设置当前区域信息
        if zone.id == current_zone_id:
            current_zone = zone_info
    
    # 按ID排序
    all_zones.sort(key=lambda z: z["id"])
    
    return await render_template("fishing_zones.html",
                                  current_zone=current_zone,
                                  all_zones=all_zones)
