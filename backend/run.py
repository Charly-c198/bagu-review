"""本地开发启动脚本：python run.py"""

from __future__ import annotations

import uvicorn

from app.config import HOST, PORT

if __name__ == "__main__":
    uvicorn.run("app.main:app", host=HOST, port=PORT, workers=1, reload=False)
