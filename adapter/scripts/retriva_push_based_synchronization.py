# Copyright (C) 2026 Andrea Marson (am.dev.75@gmail.com)
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#         http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.

"""
title: Retriva Sync Filter
author: Andrea Marson
author_url: https://github.com/am-dev-75
version: 0.1.0
description: Push-based synchronization for the Retriva Adapter. Replaces polling by notifying the adapter immediately when files are attached to a message.
"""

import requests
from typing import Optional, Dict, Any

class Filter:
    def __init__(self):
        # Valves allow users to configure the function from the Open WebUI interface
        self.valves = {
            "adapter_url": "http://192.168.1.63:8002/api/v1/chat/message",
        }

    def filter(self, body: Dict[str, Any], __user__: Optional[Dict[str, Any]] = None, __metadata__: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
        """
        Intercepts chat messages and notifies the Retriva adapter about attached files.
        """
        print(f"RetrivaSyncFilter: processing message (chat_id={body.get('chat_id', 'unknown')})")
        # 1. Extract files
        files = body.get("files", [])
        file_ids = [f.get("id") for f in files if f.get("id")]
        
        # 2. Extract Knowledge Base (Collections) IDs
        kb_ids = []
        if "selected_collections" in body:
             kb_ids = [c.get("id") for c in body.get("selected_collections", []) if c.get("id")]

        # 3. Get last user message content
        messages = body.get("messages", [])
        last_message = ""
        if messages and messages[-1].get("role") == "user":
            last_message = messages[-1].get("content", "")

        # 4. Resolve Chat ID
        chat_id = body.get("chat_id")
        if not chat_id and __metadata__:
            chat_id = __metadata__.get("chat_id")
        
        if not chat_id:
            chat_id = "default"

        # 5. Notify Adapter via Webhook
        # This is fire-and-forget (short timeout) to avoid blocking the chat UI.
        # We only notify if there are files OR if a directive is present (starts with @@).
        if file_ids or last_message.strip().startswith("@@"):
            payload = {
                "chat_id": chat_id,
                "message": last_message,
                "file_ids": file_ids,
                "kb_ids": kb_ids
            }
            
            try:
                # We use a short timeout; the adapter handles the heavy lifting in background
                requests.post(
                    self.valves["adapter_url"],
                    json=payload,
                    timeout=2 
                )
            except Exception as e:
                # In Open WebUI functions, print() statements go to the server logs
                print(f"RetrivaSyncFilter error: {e}")

        return body
