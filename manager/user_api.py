"""
用户WebUI API路由

提供用户端WebUI所需的所有API端点
"""

from quart import Blueprint, jsonify, current_app, request, session
import functools
from astrbot.api import logger


user_api_bp = Blueprint(
    "user_api",
    __name__,
    url_prefix="/api/user"
)


def api_login_required(f):
    """API登录验证装饰器"""
    @functools.wraps(f)
    async def decorated_function(*args, **kwargs):
        if "user_id" not in session:
            return jsonify({"success": False, "message": "未登录"}), 401
        return await f(*args, **kwargs)
    return decorated_function


@user_api_bp.route("/debug/status", methods=["GET"])
async def debug_status():
    """调试端点：检查WebUI初始化状态和数据库连接"""
    try:
        status = {
            "webui_initialized": True,
            "services": {},
            "database_status": "unknown"
        }
        
        # 检查services是否存在
        try:
            user_repo = current_app.config.get("USER_REPO")
            if user_repo:
                status["services"]["user_repo"] = type(user_repo).__name__
                # 尝试查询数据库
                try:
                    test_result = user_repo.get_by_id("test_query")
                    status["database_status"] = "connected"
                    status["database_query_works"] = True
                except Exception as e:
                    status["database_status"] = "error"
                    status["database_error"] = str(e)
            else:
                status["services"]["user_repo"] = "NOT FOUND"
        except Exception as e:
            status["services"]["error"] = str(e)
        
        try:
            inventory_repo = current_app.config.get("INVENTORY_REPO")
            if inventory_repo:
                status["services"]["inventory_repo"] = type(inventory_repo).__name__
            else:
                status["services"]["inventory_repo"] = "NOT FOUND"
        except:
            pass
        
        try:
            user_service = current_app.config.get("USER_SERVICE")
            if user_service:
                status["services"]["user_service"] = type(user_service).__name__
        except:
            pass
        
        return jsonify(status)
    except Exception as e:
        logger.error(f"[WebUI] 调试端点错误: {e}")
        return jsonify({"error": str(e)}), 500


@user_api_bp.route("/info", methods=["GET"])
@api_login_required
async def get_user_info():
    """获取当前登录用户信息"""
    user_id = session.get("user_id")
    
    try:
        user_repo = current_app.config["USER_REPO"]
        logger.info(f"[WebUI] /info获取USER_REPO: {type(user_repo).__name__}")
    except KeyError as e:
        logger.error(f"[WebUI] 配置错误: USER_REPO未找到 - {e}")
        return jsonify({"success": False, "message": "系统配置错误"}), 500
    
    try:
        user = user_repo.get_by_id(user_id)
        
        if not user:
            return jsonify({"success": False, "message": "用户不存在"}), 404
        
        logger.info(f"[WebUI] 用户信息查询成功: {user_id}")
        
        return jsonify({
            "success": True,
            "data": {
                "user_id": user.user_id,
                "nickname": user.nickname,
                "coins": user.coins,
                "premium_currency": user.premium_currency,
                "total_fishing_count": user.total_fishing_count,
                "total_weight_caught": user.total_weight_caught,
                "consecutive_login_days": user.consecutive_login_days,
                "fish_pond_capacity": user.fish_pond_capacity,
                "max_coins": user.max_coins,
                "created_at": user.created_at.isoformat() if user.created_at else None,
            }
        })
    except Exception as e:
        logger.error(f"获取用户信息失败: {e}", exc_info=True)
        return jsonify({"success": False, "message": f"获取失败: {str(e)}"}), 500


@user_api_bp.route("/backpack", methods=["GET"])
@api_login_required
async def get_backpack():
    """获取背包信息（鱼、装备、道具等）"""
    user_id = session.get("user_id")
    
    try:
        inventory_repo = current_app.config["INVENTORY_REPO"]
        logger.info(f"[WebUI] /backpack获取INVENTORY_REPO: {type(inventory_repo).__name__}")
    except KeyError as e:
        logger.error(f"[WebUI] 配置错误: INVENTORY_REPO未找到 - {e}")
        return jsonify({"success": False, "message": "系统配置错误"}), 500
    
    try:
        # 获取各类物品
        fish = inventory_repo.get_fish_inventory(user_id)
        rods = inventory_repo.get_user_rod_instances(user_id)
        baits = inventory_repo.get_user_bait_inventory(user_id)
        accessories = inventory_repo.get_user_accessory_instances(user_id)
        items = inventory_repo.get_user_item_inventory(user_id)
        
        logger.info(f"[WebUI] 背包查询成功 - 鱼:{len(fish)}, 竿:{len(rods)}, 诱饵:{len(baits)}, 饰品:{len(accessories)}, 道具:{len(items)}")
        
        return jsonify({
            "success": True,
            "data": {
                "fish_count": len(fish) if fish else 0,
                "rod_count": len(rods) if rods else 0,
                "bait_count": len(baits) if baits else 0,
                "accessory_count": len(accessories) if accessories else 0,
                "item_count": len(items) if items else 0,
            }
        })
    except Exception as e:
        logger.error(f"获取背包信息失败: {e}", exc_info=True)
        return jsonify({"success": False, "message": f"获取失败: {str(e)}"}), 500


@user_api_bp.route("/fish", methods=["GET"])
@api_login_required
async def get_fish():
    """获取用户的鱼塘中的鱼"""
    user_id = session.get("user_id")
    
    try:
        inventory_repo = current_app.config["INVENTORY_REPO"]
        logger.info(f"[WebUI] /fish获取INVENTORY_REPO: {type(inventory_repo).__name__}")
    except KeyError as e:
        logger.error(f"[WebUI] 配置错误: INVENTORY_REPO未找到 - {e}")
        return jsonify({"success": False, "message": "系统配置错误"}), 500
    
    try:
        fish = inventory_repo.get_fish_inventory(user_id)
        
        fish_list = []
        if fish:
            for f in fish:
                fish_list.append({
                    "fish_id": f.fish_id,
                    "quality_level": f.quality_level,
                    "quantity": f.quantity,
                })
        
        logger.info(f"[WebUI] 鱼列表查询成功: {len(fish_list)}条鱼")
        
        return jsonify({
            "success": True,
            "data": fish_list
        })
    except Exception as e:
        logger.error(f"获取鱼列表失败: {e}", exc_info=True)
        return jsonify({"success": False, "message": f"获取失败: {str(e)}"}), 500


@user_api_bp.route("/rods", methods=["GET"])
@api_login_required
async def get_rods():
    """获取用户的鱼竿"""
    user_id = session.get("user_id")
    
    try:
        inventory_repo = current_app.config["INVENTORY_REPO"]
        logger.info(f"[WebUI] /rods获取INVENTORY_REPO: {type(inventory_repo).__name__}")
    except KeyError as e:
        logger.error(f"[WebUI] 配置错误: INVENTORY_REPO未找到 - {e}")
        return jsonify({"success": False, "message": "系统配置错误"}), 500
    
    try:
        rods = inventory_repo.get_user_rod_instances(user_id)
        
        rod_list = []
        if rods:
            for r in rods:
                rod_list.append({
                    "rod_id": r.rod_id,
                    "durability": r.durability if hasattr(r, 'durability') else 0,
                })
        
        logger.info(f"[WebUI] 鱼竿列表查询成功: {len(rod_list)}根鱼竿")
        
        return jsonify({
            "success": True,
            "data": rod_list
        })
    except Exception as e:
        logger.error(f"获取鱼竿列表失败: {e}", exc_info=True)
        return jsonify({"success": False, "message": f"获取失败: {str(e)}"}), 500


@user_api_bp.route("/baits", methods=["GET"])
@api_login_required
async def get_baits():
    """获取用户的鱼饵"""
    user_id = session.get("user_id")
    
    try:
        inventory_repo = current_app.config["INVENTORY_REPO"]
        logger.info(f"[WebUI] /baits获取INVENTORY_REPO: {type(inventory_repo).__name__}")
    except KeyError as e:
        logger.error(f"[WebUI] 配置错误: INVENTORY_REPO未找到 - {e}")
        return jsonify({"success": False, "message": "系统配置错误"}), 500
    
    try:
        baits = inventory_repo.get_user_bait_inventory(user_id)
        
        bait_list = []
        if baits:
            for b in baits:
                bait_list.append({
                    "bait_id": b.bait_id,
                    "quantity": b.quantity,
                })
        
        logger.info(f"[WebUI] 鱼饵列表查询成功: {len(bait_list)}种鱼饵")
        
        return jsonify({
            "success": True,
            "data": bait_list
        })
    except Exception as e:
        logger.error(f"获取鱼饵列表失败: {e}", exc_info=True)
        return jsonify({"success": False, "message": f"获取失败: {str(e)}"}), 500


@user_api_bp.route("/accessories", methods=["GET"])
@api_login_required
async def get_accessories():
    """获取用户的饰品"""
    user_id = session.get("user_id")
    
    try:
        inventory_repo = current_app.config["INVENTORY_REPO"]
        logger.info(f"[WebUI] /accessories获取INVENTORY_REPO: {type(inventory_repo).__name__}")
    except KeyError as e:
        logger.error(f"[WebUI] 配置错误: INVENTORY_REPO未找到 - {e}")
        return jsonify({"success": False, "message": "系统配置错误"}), 500
    
    try:
        accessories = inventory_repo.get_user_accessory_instances(user_id)
        
        acc_list = []
        if accessories:
            for a in accessories:
                acc_list.append({
                    "accessory_id": a.accessory_id,
                    "durability": a.durability if hasattr(a, 'durability') else 0,
                })
        
        logger.info(f"[WebUI] 饰品列表查询成功: {len(acc_list)}个饰品")
        
        return jsonify({
            "success": True,
            "data": acc_list
        })
    except Exception as e:
        logger.error(f"获取饰品列表失败: {e}", exc_info=True)
        return jsonify({"success": False, "message": f"获取失败: {str(e)}"}), 500


@user_api_bp.route("/items", methods=["GET"])
@api_login_required
async def get_items():
    """获取用户的道具"""
    user_id = session.get("user_id")
    
    try:
        inventory_repo = current_app.config["INVENTORY_REPO"]
        logger.info(f"[WebUI] /items获取INVENTORY_REPO: {type(inventory_repo).__name__}")
    except KeyError as e:
        logger.error(f"[WebUI] 配置错误: INVENTORY_REPO未找到 - {e}")
        return jsonify({"success": False, "message": "系统配置错误"}), 500
    
    try:
        items = inventory_repo.get_user_item_inventory(user_id)
        
        item_list = []
        if items:
            for i in items:
                item_list.append({
                    "item_id": i.item_id,
                    "quantity": i.quantity,
                })
        
        logger.info(f"[WebUI] 道具列表查询成功: {len(item_list)}种道具")
        
        return jsonify({
            "success": True,
            "data": item_list
        })
    except Exception as e:
        logger.error(f"获取道具列表失败: {e}", exc_info=True)
        return jsonify({"success": False, "message": f"获取失败: {str(e)}"}), 500



@user_api_bp.route("/fishing/do", methods=["POST"])
@api_login_required
async def do_fishing():
    """执行钓鱼操作"""
    user_id = session.get("user_id")
    
    try:
        user_repo = current_app.config["USER_REPO"]
        logger.info(f"[WebUI] /fishing/do获取USER_REPO: {type(user_repo).__name__}")
    except KeyError as e:
        logger.error(f"[WebUI] 配置错误: USER_REPO未找到 - {e}")
        return jsonify({"success": False, "message": "系统配置错误"}), 500
    
    try:
        fishing_service = current_app.config["FISHING_SERVICE"]
        logger.info(f"[WebUI] /fishing/do获取FISHING_SERVICE: {type(fishing_service).__name__}")
    except KeyError as e:
        logger.error(f"[WebUI] 配置错误: FISHING_SERVICE未找到 - {e}")
        return jsonify({"success": False, "message": "系统配置错误"}), 500
    
    try:
        user = user_repo.get_by_id(user_id)
        if not user:
            return jsonify({"success": False, "message": "用户不存在"}), 404
        
        # 执行钓鱼
        result = fishing_service.fish(user_id, None)  # None表示使用当前区域
        
        logger.info(f"[WebUI] 钓鱼执行成功: {user_id}")
        
        return jsonify({
            "success": result.get("success", False),
            "message": result.get("message", "钓鱼失败"),
            "data": result.get("data")
        })
    except Exception as e:
        logger.error(f"钓鱼失败: {e}", exc_info=True)
        return jsonify({"success": False, "message": f"钓鱼失败: {str(e)}"}), 500


@user_api_bp.route("/sign-in", methods=["POST"])
@api_login_required
async def sign_in():
    """用户签到"""
    user_id = session.get("user_id")
    
    try:
        user_service = current_app.config["USER_SERVICE"]
        logger.info(f"[WebUI] /sign-in获取USER_SERVICE: {type(user_service).__name__}")
    except KeyError as e:
        logger.error(f"[WebUI] 配置错误: USER_SERVICE未找到 - {e}")
        return jsonify({"success": False, "message": "系统配置错误"}), 500
    
    try:
        result = user_service.sign_in(user_id)
        
        logger.info(f"[WebUI] 签到成功: {user_id}")
        
        return jsonify({
            "success": result.get("success", False),
            "message": result.get("message", "签到失败")
        })
    except Exception as e:
        logger.error(f"签到失败: {e}", exc_info=True)
        return jsonify({"success": False, "message": f"签到失败: {str(e)}"}), 500


@user_api_bp.route("/market/list", methods=["GET"])
@api_login_required
async def get_market_listings():
    """获取市场列表"""
    try:
        market_service = current_app.config["MARKET_SERVICE"]
        logger.info(f"[WebUI] /market/list获取MARKET_SERVICE: {type(market_service).__name__}")
    except KeyError as e:
        logger.error(f"[WebUI] 配置错误: MARKET_SERVICE未找到 - {e}")
        return jsonify({"success": False, "message": "系统配置错误"}), 500
    
    try:
        page = int(request.args.get("page", 1))
        per_page = int(request.args.get("per_page", 20))
        item_type = request.args.get("item_type")
        min_price = request.args.get("min_price")
        max_price = request.args.get("max_price")
        
        min_price = int(min_price) if min_price else None
        max_price = int(max_price) if max_price else None
        
        result = market_service.get_all_market_listings_for_admin(
            page=page,
            per_page=per_page,
            item_type=item_type,
            min_price=min_price,
            max_price=max_price
        )
        
        logger.info(f"[WebUI] 市场列表查询成功")
        
        return jsonify({
            "success": result.get("success", False),
            "data": result.get("listings", []),
            "pagination": result.get("pagination", {})
        })
    except Exception as e:
        logger.error(f"获取市场列表失败: {e}", exc_info=True)
        return jsonify({"success": False, "message": f"获取失败: {str(e)}"}), 500


@user_api_bp.route("/market/list/<int:listing_id>", methods=["POST"])
@api_login_required
async def purchase_listing(listing_id):
    """购买市场商品"""
    user_id = session.get("user_id")
    
    try:
        market_service = current_app.config["MARKET_SERVICE"]
        logger.info(f"[WebUI] /market/list/<id>获取MARKET_SERVICE: {type(market_service).__name__}")
    except KeyError as e:
        logger.error(f"[WebUI] 配置错误: MARKET_SERVICE未找到 - {e}")
        return jsonify({"success": False, "message": "系统配置错误"}), 500
    
    try:
        result = market_service.purchase_item(user_id, listing_id)
        
        logger.info(f"[WebUI] 购买成功: {user_id} -> {listing_id}")
        
        return jsonify({
            "success": result.get("success", False),
            "message": result.get("message", "购买失败")
        })
    except Exception as e:
        logger.error(f"购买失败: {e}", exc_info=True)
        return jsonify({"success": False, "message": f"购买失败: {str(e)}"}), 500


@user_api_bp.route("/shop/list", methods=["GET"])
@api_login_required
async def get_shops():
    """获取商店列表"""
    try:
        item_template_service = current_app.config["ITEM_TEMPLATE_SERVICE"]
        logger.info(f"[WebUI] /shop/list获取ITEM_TEMPLATE_SERVICE: {type(item_template_service).__name__}")
    except KeyError as e:
        logger.error(f"[WebUI] 配置错误: ITEM_TEMPLATE_SERVICE未找到 - {e}")
        return jsonify({"success": False, "message": "系统配置错误"}), 500
    
    try:
        shops = item_template_service.get_all_shops()
        
        shop_list = []
        if shops:
            for shop in shops:
                shop_list.append({
                    "id": shop.id,
                    "name": shop.name,
                    "description": shop.description,
                    "shop_type": shop.shop_type,
                })
        
        logger.info(f"[WebUI] 商店列表查询成功: {len(shop_list)}个商店")
        
        return jsonify({
            "success": True,
            "data": shop_list
        })
    except Exception as e:
        logger.error(f"获取商店列表失败: {e}", exc_info=True)
        return jsonify({"success": False, "message": f"获取失败: {str(e)}"}), 500


@user_api_bp.route("/gacha/do", methods=["POST"])
@api_login_required
async def do_gacha():
    """执行抽卡"""
    user_id = session.get("user_id")
    
    try:
        gacha_service = current_app.config["GACHA_SERVICE"]
        logger.info(f"[WebUI] /gacha/do获取GACHA_SERVICE: {type(gacha_service).__name__}")
    except KeyError as e:
        logger.error(f"[WebUI] 配置错误: GACHA_SERVICE未找到 - {e}")
        return jsonify({"success": False, "message": "系统配置错误"}), 500
    
    try:
        form = await request.json
        gacha_type = form.get("type", "single")  # single or ten
        
        if gacha_type == "ten":
            result = gacha_service.ten_gacha(user_id)
        else:
            result = gacha_service.single_gacha(user_id)
        
        logger.info(f"[WebUI] 抽卡成功: {user_id} ({gacha_type})")
        
        return jsonify({
            "success": result.get("success", False),
            "message": result.get("message", "抽卡失败"),
            "data": result.get("data")
        })
    except Exception as e:
        logger.error(f"抽卡失败: {e}", exc_info=True)
        return jsonify({"success": False, "message": f"抽卡失败: {str(e)}"}), 500


@user_api_bp.route("/leaderboard", methods=["GET"])
@api_login_required
async def get_leaderboard():
    """获取排行榜"""
    try:
        user_service = current_app.config["USER_SERVICE"]
        logger.info(f"[WebUI] /leaderboard获取USER_SERVICE: {type(user_service).__name__}")
    except KeyError as e:
        logger.error(f"[WebUI] 配置错误: USER_SERVICE未找到 - {e}")
        return jsonify({"success": False, "message": "系统配置错误"}), 500
    
    try:
        sort_by = request.args.get("sort_by", "coins")
        limit = int(request.args.get("limit", 10))
        
        result = user_service.get_leaderboard_data(sort_by=sort_by, limit=limit)
        
        logger.info(f"[WebUI] 排行榜查询成功: {sort_by}")
        
        return jsonify({
            "success": result.get("success", False),
            "data": result.get("leaderboard", [])
        })
    except Exception as e:
        logger.error(f"获取排行榜失败: {e}", exc_info=True)
        return jsonify({"success": False, "message": f"获取失败: {str(e)}"}), 500


@user_api_bp.route("/profile/update", methods=["POST"])
@api_login_required
async def update_profile():
    """更新用户信息"""
    user_id = session.get("user_id")
    
    try:
        user_repo = current_app.config["USER_REPO"]
        logger.info(f"[WebUI] /profile/update获取USER_REPO: {type(user_repo).__name__}")
    except KeyError as e:
        logger.error(f"[WebUI] 配置错误: USER_REPO未找到 - {e}")
        return jsonify({"success": False, "message": "系统配置错误"}), 500
    
    try:
        form = await request.json
        nickname = form.get("nickname", "").strip()
        
        if not nickname or len(nickname) < 2 or len(nickname) > 20:
            return jsonify({"success": False, "message": "昵称长度必须为2-20个字符"})
        
        user = user_repo.get_by_id(user_id)
        if user:
            user.nickname = nickname
            user_repo.update(user)
            
            logger.info(f"[WebUI] 用户信息更新成功: {user_id}")
            
            return jsonify({"success": True, "message": "昵称更新成功"})
        
        return jsonify({"success": False, "message": "用户不存在"})
    except Exception as e:
        logger.error(f"更新用户信息失败: {e}", exc_info=True)
        return jsonify({"success": False, "message": f"更新失败: {str(e)}"}), 500


@user_api_bp.route("/fish-templates", methods=["GET"])
@api_login_required
async def get_fish_templates():
    """获取所有鱼类模板（用于图鉴）"""
    try:
        item_template_service = current_app.config["ITEM_TEMPLATE_SERVICE"]
        logger.info(f"[WebUI] /fish-templates获取ITEM_TEMPLATE_SERVICE: {type(item_template_service).__name__}")
    except KeyError as e:
        logger.error(f"[WebUI] 配置错误: ITEM_TEMPLATE_SERVICE未找到 - {e}")
        return jsonify({"success": False, "message": "系统配置错误"}), 500
    
    try:
        fish_templates = item_template_service.get_all_fish_templates()
        
        fish_list = []
        if fish_templates:
            for fish in fish_templates:
                fish_list.append({
                    "id": fish.id,
                    "name": fish.name,
                    "description": fish.description or "",
                    "quality_level": fish.quality_level or 1,
                    "weight": fish.weight or 0,
                    "drop_rate": fish.drop_rate or 0,
                    "zones": fish.zones or "",
                })
        
        logger.info(f"[WebUI] 鱼类模板查询成功: {len(fish_list)}条")
        
        return jsonify({
            "success": True,
            "data": fish_list
        })
    except Exception as e:
        logger.error(f"获取鱼类模板失败: {e}", exc_info=True)
        return jsonify({"success": False, "message": f"获取失败: {str(e)}"}), 500
