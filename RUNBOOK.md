你将以三角色模式完成本项目开发：

阶段 1：Product Manager
- 输出 PRD.md
- 必须包含用户故事、验收标准、页面架构、数据模型
- 不允许写代码

阶段 2：Developer
- 技术栈：FastAPI + Jinja2 + TailwindCSS + SQLite
- 必须生成 ARCH.md、README.md
- 代码必须可运行
- 提供 Dockerfile 和 docker-compose.yml

阶段 3：QA
- 编写 pytest 自动化测试
- 覆盖所有验收标准
- 执行测试并输出 TESTREPORT.md
- 如果测试失败必须修复

规则：
- 每个阶段结束必须提交文件
- 测试不通过不允许完成任务
- 所有改动必须落地到文件
- 所有命令必须执行并给出输出摘要
