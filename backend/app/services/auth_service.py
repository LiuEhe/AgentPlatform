"""注册、登录及账号凭据生命周期。"""

import hashlib
import logging
import secrets
from datetime import UTC, datetime, timedelta

from app.core.errors import AppError
from app.schemas.identity import LoginGrant, normalize_username

logger = logging.getLogger(__name__)


class AuthService:
    def __init__(self, settings, store, passwords, limits):
        self.settings, self.store = settings, store
        self.passwords, self.limits = passwords, limits
        self._dummy_hash = None

    async def initialize(self):
        await self.store.assert_bootstrap_admin()
        self._dummy_hash = await self.passwords.hash(secrets.token_urlsafe(15))

    async def register(self, username, display_name, password, *, source_ip):
        remaining = self.limits.reserve_registration(source_ip)
        if remaining:
            raise AppError("REGISTRATION_RATE_LIMITED", "注册尝试过于频繁，请稍后重试", 429,
                           retry_after_seconds=remaining)
        encoded = await self.passwords.hash(password)
        user = await self.store.register_user(normalize_username(username), display_name, encoded)
        logger.info("identity_event operation=register target=%s", user.user_id)
        return user

    async def authenticate(self, cookie_token):
        if not cookie_token or len(cookie_token) > 256:
            raise AppError("AUTH_REQUIRED", "请先登录", 401)
        return await self.store.read_context(hashlib.sha256(cookie_token.encode()).digest())

    async def assert_live(self, context):
        return await self.store.assert_live(context)

    async def login(self, username, password, *, source_ip, old_token=None):
        username = normalize_username(username)
        remaining = self.limits.check_login(source_ip, username)
        if remaining:
            raise AppError("LOGIN_RATE_LIMITED", "登录尝试过于频繁，请稍后重试", 429,
                           retry_after_seconds=remaining)
        record = await self.store.find_user(username)
        verification = await self.passwords.verify(
            password, record.password_hash if record else self._dummy_hash,
        )
        if record is None or not verification.valid or record.identity.status != "active":
            self.limits.failed_login(source_ip, username)
            logger.info("identity_event operation=login_failed")
            raise AppError("INVALID_CREDENTIALS", "用户名或密码错误", 401)
        old_id = None
        if old_token:
            try:
                old_id = (await self.authenticate(old_token)).auth_session_id
            except AppError as exc:
                if exc.code != "AUTH_REQUIRED":
                    raise
        cookie_token = secrets.token_urlsafe(32)
        context = await self.store.issue_session(
            record.identity.user_id, record.password_hash, old_id,
            hashlib.sha256(cookie_token.encode()).digest(), secrets.token_urlsafe(32),
            datetime.now(UTC) + timedelta(seconds=self.settings.auth_session_ttl_seconds),
            replacement_hash=verification.replacement_hash,
        )
        self.limits.succeeded_login(source_ip, username)
        logger.info("identity_event operation=login target=%s", record.identity.user_id)
        return LoginGrant(context, cookie_token)

    async def logout(self, actor):
        try:
            await self.store.revoke_session(actor)
        except AppError as exc:
            if exc.code != "AUTH_REQUIRED":
                raise
        logger.info("identity_event operation=logout actor=%s", actor.user.user_id)

    async def change_password(self, actor, current_password, new_password):
        record = await self.store.find_user(actor.user.username)
        if record is None or not (await self.passwords.verify(
            current_password, record.password_hash,
        )).valid:
            raise AppError("PASSWORD_INVALID", "当前密码错误", 422)
        if current_password == new_password:
            raise AppError("PASSWORD_INVALID", "新密码不能与当前密码相同", 422)
        encoded = await self.passwords.hash(new_password)
        await self.store.change_password(actor, record.password_hash, encoded)
        logger.info("identity_event operation=password_change actor=%s", actor.user.user_id)
