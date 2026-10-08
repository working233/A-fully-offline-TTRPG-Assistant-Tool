# 本地跑团辅助工具（TRPG Local Assistant）

一款**完全离线**的跑团辅助工具：跑团 / 角色卡 / 怪物卡 / 骰子 / 地图 / 剧情 / 记录全在一台机器上，
数据就是一堆可读的 JSON 文件，**没有一个字节上传到云端**，也不需要安装数据库或 npm 依赖。

## 🚀 傻瓜式启动（不用记命令）

### 方式一：双击（Windows，推荐）

进到项目根目录，双击 **`启动跑团工具.bat`**。它会自动做完 4 件事：

1. **找 Python**：依次尝试 `py -3` / `python` / `python3`，再兜底查找常见安装目录；版本低于 3.11 会明确报错并给出下载链接；
2. **跑自检**：执行 `--doctor`，显示 Python 版本、数据目录、跑团数量、剧情是否断链；
3. **启动**：起本地服务器并自动打开浏览器，终端里会打印访问地址；
4. **防闪退**：任何一步失败都会暂停并给出排错提示，不会一闪而过。

> 想带参数用：`启动跑团工具.bat --no-open --port 9000`（把文件拖到「命令提示符」窗口里再加参数即可）

**分工（很重要）**：`.bat` 本身是纯 ASCII 英文，只负责「找到 Python」，找到之后就把活交给 `start.py`，
所有中文提示由 Python 输出。这么做是因为 **cmd.exe 处理中文/UTF-8 批处理时会算错文件偏移，
把正常的一行行命令撕成一堆碎片去执行**（表现就是满屏「…不是内部或外部命令」）。
所以别把 `.bat` 改成中文，也别另存成 UTF-8 编码。

### 方式二：双击 `start.py`（Windows / macOS / Linux 通用）

`start.py` 与 `.bat` 做同样的事，跨平台版。Windows 双击即可，Mac/Linux 终端执行 `python3 start.py`，参数原样透传。

### 方式三：命令行（老手）

要求：**Python 3.11+**，零第三方依赖，不用 `pip install` 任何东西。

```bash
python -m app.main                 # 一键启动：自动挑端口 + 自动开浏览器
```

浏览器会自动打开 Web 编辑器。**关掉浏览器，服务会在约 25 秒后自动退出**，不留后台进程。

## 常用命令

| 命令 | 作用 |
|---|---|
| `python -m app.main` | 启动本地服务器并打开浏览器 |
| `python -m app.main --no-open` | 只启动服务，不自动开浏览器（方便手动/另一窗口访问） |
| `python -m app.main --port 9000` | 指定端口（默认自动在 8765~8804 里挑一个空闲端口） |
| `python -m app.main --data-dir D:\trpg` | 指定数据目录（也可用环境变量 `TRPG_HOME`） |
| `python -m app.main --doctor` | 环境自检：目录、跑团、剧情图谱、回收站、备份 |
| `python -m app.main --backup` | 立即生成一次全量备份 zip |
| `python -m app.main --seed-demo` | 导入/重新导入示例跑团 |
| `python app/services/dice_service.py` | 单独跑骰子模块 demo（无需启动服务） |

### 双击失败怎么排查

| 现象 | 原因 / 处理 |
|---|---|
| 黑窗口一闪而过 | 多数是没装 Python。改用 cmd 执行 `python -m app.main` 就能看到完整报错 |
| 中文乱码 | 脚本已切换 UTF-8 代码页；仍乱码时把 `.bat` 另存为 UTF-8 编码再双击 |
| 提示端口被占用 | 换端口：`启动跑团工具.bat --port 9000` |
| 浏览器没自动打开 | 黑窗口里会打印「访问地址」，手动复制到浏览器即可 |
| 提示找不到 app/main.py | 确认 `.bat` 就在项目根目录（与 README.md 同级） |

## 功能地图

| 模块 | 已实现 | 说明 |
|---|---|---|
| 跑团管理 | ✅ | 创建/切换/删除，自动生成 characters、monsters、maps、notes、stories、logs、assets |
| 角色卡 / 怪物卡 | ✅ | 模板化生成（DND 5e / COC 7th），Schema 驱动动态表单，HP 快捷调整 |
| 骰子系统 | ✅ | d4~d100、任意表达式、`4d6kh3` / `d20 adv`、调整值、期望值、**精确概率**、历史与统计 |
| 地图管理 | 🟡 数据层 | `maps/*.map.json` 已定义网格 / 六边形 / 迷雾 / 光源 / token，渲染视图待补（路线图 P0） |
| 剧情管理 | ✅ | 主线/分支/结局节点、条件跳转、拖拽布局、图谱校验、DOT 导出 |
| 跑团记录 | ✅ | 时间线日志（jsonl）、玩家花名册、LOOT 台账、Markdown 导出 |
| 安全与备份 | ✅ | 隐藏删除+回收站还原、原子写、路径越界防护、zip 备份与轮转 |

🟡 = 数据模型与后端接口就绪，前端渲染待补。

## 目录速览

```
app/core       路径 / 原子 IO / 校验 / 安全守卫 / 事件总线（纯内核）
app/services   Campaign / FileManager / Trash / Dice / Entity / Story / Record / Backup
app/api.py     REST 路由（唯一对外契约）
app/server.py  回环绑定 + 自动端口 + 心跳看门狗
web/           原生 HTML/CSS/JS 编辑器，无构建步骤
docs/          技术方案、界面说明
samples/       示例跑团（含一人一怪一篇剧情）
```

数据目录默认 `~/TRPG-Local-Assistant`，结构见 `docs/技术方案.md §3`。

## 数据是你的

- 所有写操作只落在自己的数据目录，**没有任何外发网络请求**。
- 删除一律进 `_trash` 而非物理删除，随时在「回收站 / 备份」里还原。
- `_backups` 下是完整 zip，拷到 U 盘或网盘即可迁移；换机器后点「还原」继续跑。

更详细的架构、数据模型与扩展方案（多人联机 / DOT→SVG / AI 辅助 / 自定义规则）见 `docs/技术方案.md`。
