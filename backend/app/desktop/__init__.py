"""桌面端（Agent Desktop）后端支持。

模块划分：

- ``launcher``  —— sidecar 启动器：自绑 loopback 套接字 + 握手输出；
- ``bootstrap`` —— 会话引导与访问边界（令牌 / Cookie / Host 白名单）；
- ``events``    —— 后端 → 壳 的事件总线。
"""
