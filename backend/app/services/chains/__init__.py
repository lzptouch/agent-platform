"""扩展链（S6）：技能规范 / 索引 / 扫描 / 插件包。

- ``skills.spec``：SKILL.md front matter 规范与校验；
- ``skills.index``：轻量索引（只读 front matter，命中才读正文）；
- ``skills.scanner``：静态扫描规则集（七项规则 + 分级）；
- ``skills.plugins``：插件包安装（原子切换）与回滚。
"""
