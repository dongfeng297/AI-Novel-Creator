# AI Novel

本地单机 Web 小说创作工作台，覆盖以下核心能力：

- 作品、章节、世界观管理
- 角色库与角色卡管理
- 词条库与词条卡管理
- 章节生成时手动选择或按名称自动加载角色卡/词条卡
- 每章同时生成正文和摘要
- 生成后正文可继续编辑并保存
- 章节生成后自动最小化更新角色卡/词条卡动态信息

## Run

```bash
npm start
```

默认启动地址：

```text
http://localhost:3000
```

## AI Model

默认不配置模型也能运行，此时会使用本地回退草稿模式验证流程。

如需接入 OpenAI 兼容接口，可设置：

```bash
export OPENAI_API_KEY=your_key
export OPENAI_BASE_URL=https://api.openai.com/v1
export OPENAI_MODEL=gpt-4.1-mini
python3 server.py
```

## Storage

应用数据保存在：

```text
data/store.json
```

## Backend

后端已重构为 Python 标准库实现，入口文件为：

```text
server.py
```
