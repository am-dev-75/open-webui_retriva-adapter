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

import sqlite3
import os

db_path = "data/adapter.db"
if os.path.exists(db_path):
    conn = sqlite3.connect(db_path)
    cursor = conn.cursor()
    try:
        cursor.execute("DELETE FROM kb_mappings WHERE owui_kb_id LIKE 'KB_REPRO_%';")
        cursor.execute("DELETE FROM file_mappings WHERE owui_file_id LIKE 'f-repro-%';")
        conn.commit()
        print("Test data cleaned up.")
    except Exception as e:
        print(f"Error: {e}")
    finally:
        conn.close()
