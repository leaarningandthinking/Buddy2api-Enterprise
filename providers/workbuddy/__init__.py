"""WorkBuddy provider facade. Implementation stays in proxy.py / auth_manager.py."""

from __future__ import annotations

from typing import Optional

import auth_manager
import proxy
from providers.protocol import ChannelId


class WorkBuddyProvider:
    id: ChannelId = "workbuddy"
    display_name = "WorkBuddy / CodeBuddy"
    checkin_supported = True

    def list_models(self) -> list[dict]:
        import catalog

        return catalog.models_for(self.id, catalog.workbuddy_fallback_models())

    def alias_map(self) -> dict[str, str]:
        import aliases

        return aliases.merged_map(self.id)

    def accepts_model(self, inner: str) -> bool:
        ids = {str(item.get("id")) for item in self.list_models() if isinstance(item, dict)}
        return inner in ids or inner in self.alias_map()

    def translate_model(self, model: str) -> str:
        import aliases

        return aliases.resolve(self.id, model)

    def pick_account(self, exclude_ids: set[int] | None = None) -> Optional[dict]:
        return auth_manager.pick_account(exclude_ids, provider=self.id)

    async def pick_account_with_fallback(
        self, exclude_ids: set[int] | None = None
    ) -> Optional[dict]:
        return await auth_manager.pick_account_with_fallback(exclude_ids, provider=self.id)

    async def has_usable_account(self) -> bool:
        return await self.pick_account_with_fallback() is not None

    async def chat_completions(self, payload: dict, api_key_info: dict | None) -> tuple:
        log_model = None
        info = api_key_info
        if isinstance(api_key_info, dict) and "_log_model" in api_key_info:
            log_model = api_key_info.get("_log_model")
            info = {k: v for k, v in api_key_info.items() if k != "_log_model"} or None
        return await proxy.proxy_chat_completions(payload, info, log_model=log_model)


PROVIDER = WorkBuddyProvider()
