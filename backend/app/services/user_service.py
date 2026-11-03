"""本人资料和管理员账号管理用例。"""

import logging

logger = logging.getLogger(__name__)


class UserService:
    def __init__(self, store, passwords):
        self.store, self.passwords = store, passwords

    async def update_profile(self, actor, display_name):
        return await self.store.update_profile(actor, display_name)

    async def create_user(self, actor, username, display_name, temporary_password):
        user = await self.store.create_user(
            actor, username, display_name, await self.passwords.hash(temporary_password),
        )
        logger.info("identity_event operation=create_user actor=%s target=%s",
                    actor.user.user_id, user.user_id)
        return user

    async def set_status(self, actor, target_user_id, status):
        user = await self.store.set_status(actor, target_user_id, status)
        logger.info("identity_event operation=set_status actor=%s target=%s status=%s",
                    actor.user.user_id, target_user_id, status)
        return user

    async def reset_password(self, actor, target_user_id, temporary_password):
        await self.store.reset_password(
            actor, target_user_id, await self.passwords.hash(temporary_password),
        )
        logger.info("identity_event operation=password_reset actor=%s target=%s",
                    actor.user.user_id, target_user_id)

    async def list_users(self, actor, *, limit=20, cursor=None):
        return await self.store.list_users(actor, limit=limit, cursor=cursor)
