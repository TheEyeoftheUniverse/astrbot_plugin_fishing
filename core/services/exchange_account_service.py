from typing import Dict, Any

from astrbot.api import logger

from ..domain.models import User
from ..repositories.abstract_repository import AbstractUserRepository


class ExchangeAccountService:
    """交易所账户管理服务"""
    
    def __init__(self, user_repo: AbstractUserRepository, config: Dict[str, Any] = None):
        self.user_repo = user_repo
        self.config = config or {}

    def open_exchange_account(self, user_id: str) -> Dict[str, Any]:
        """开通交易所账户"""
        try:
            # 检查用户是否存在
            user = self.user_repo.get_by_id(user_id)
            if not user:
                return {"success": False, "message": "用户不存在"}
            
            # 检查是否已经开通
            if hasattr(user, 'exchange_account_status') and user.exchange_account_status:
                return {"success": False, "message": "您已经开通了交易所账户"}
            
            # 获取开户费用
            account_fee = self.config.get("account_fee", 100000)
            
            # 检查金币是否足够
            if user.coins < account_fee:
                return {"success": False, "message": f"金币不足！开通交易所账户需要 {account_fee:,} 金币，您当前只有 {user.coins:,} 金币"}
            
            # 扣除金币
            user.coins -= account_fee
            
            # 开通账户
            user.exchange_account_status = True
            self.user_repo.update(user)
            
            return {"success": True, "message": f"交易所账户开通成功！已扣除 {account_fee:,} 金币"}
        except Exception as e:
            logger.error(f"开通交易所账户失败: {e}")
            return {"success": False, "message": f"开通失败: {str(e)}"}

    def check_exchange_account(self, user_id: str) -> Dict[str, Any]:
        """检查交易所账户状态"""
        try:
            # 检查用户是否存在
            user = self.user_repo.get_by_id(user_id)
            if not user:
                return {"success": False, "message": "用户不存在"}
            
            # 检查是否已开通
            if not hasattr(user, 'exchange_account_status') or not user.exchange_account_status:
                return {"success": False, "message": "您还没有开通交易所账户，请先使用「交易所 开户」开通"}
            
            return {"success": True, "message": "账户状态正常"}
        except Exception as e:
            logger.error(f"检查交易所账户失败: {e}")
            return {"success": False, "message": f"检查失败: {str(e)}"}
