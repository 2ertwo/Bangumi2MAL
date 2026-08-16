# Bangumi2MAL

一个面向单用户、自托管的 Bangumi → MyAnimeList 单向迁移与自动同步工具。

它包含两个入口，但只维护一套同步核心：

- CLI：执行 dry-run 或真实同步，并将结果导出为 CSV。
- Flask Web UI：密码登录、MAL OAuth、同步历史、人工条目映射和定时同步。

项目刻意保持轻量：Flask 默认 Jinja 模板、Bootstrap CDN、Python 内置 `sqlite3`，不需要 Node.js、Redis 或独立数据库服务器。

## 当前同步范围

- Bangumi 收藏状态 → MAL 列表状态
- Bangumi 评分（未评分时不会清空 MAL 评分）
- 已观看集数（默认不会降低 MAL 中已有的集数）
- 不删除 MAL 独有条目
- 先按原名、中文名和多语言别名搜索；无法确定时再按 Bangumi 开播季度扫描 MAL 季度全集，并结合具体开播日期复核
- 高置信度自动匹配；模糊条目留给人工确认

状态映射：

| Bangumi | MyAnimeList |
|---|---|
| 想看 | `plan_to_watch` |
| 看过 | `completed` |
| 在看 | `watching` |
| 搁置 | `on_hold` |
| 抛弃 | `dropped` |

## 本地安装

需要 Python 3.9 或更高版本。

### Windows PowerShell

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install --upgrade pip
pip install -e ".[dev]"
Copy-Item .env.example .env
```

### Ubuntu

```bash
python3 -m venv .venv
source .venv/bin/activate
python -m pip install --upgrade pip
pip install -e '.[dev,deploy]'
cp .env.example .env
```

## 推荐：一条命令完成配置

首次安装后直接运行：

`ash
bangumi2mal setup
`

部署到已有域名的 Ubuntu 服务器时：

`ash
bangumi2mal setup --base-url https://sync.example.com --no-browser
`

向导会自动打开凭据页面、从 Bangumi token 识别用户名、计算 MAL Redirect URL、哈希 Web 密码、生成 Flask secret、写入并保护 .env、初始化 SQLite，然后继续完成 MAL OAuth。

由于 Bangumi 和 MAL 的安全限制，个人 access token 与 MAL API Client 仍必须由账号本人在官网创建；向导会打开准确页面，两个凭据都只需粘贴一次，不再需要手工复制配置项、密码哈希或 callback URL。

如果暂时不想完成 MAL OAuth，可使用：

`ash
bangumi2mal setup --skip-mal-auth
`

以后再运行 angumi2mal auth-mal 即可。重复运行 setup 会复用已有设置，不会再次询问已经配置的值。

## 手工配置（可选）

编辑 `.env`：

1. 在 [Bangumi API 文档](https://bangumi.github.io/api/)所指向的用户授权页面创建个人 access token，设置 `BANGUMI_USERNAME` 和 `BANGUMI_ACCESS_TOKEN`。
2. 在 [MyAnimeList API Client](https://myanimelist.net/apiconfig/create) 注册应用，设置 `MAL_CLIENT_ID`；有 secret 时一并设置。
3. MAL 应用的 Redirect URL 必须和 `MAL_REDIRECT_URI` 完全一致。本地默认是 `http://127.0.0.1:5000/oauth/mal/callback`。
4. 生成 Web 密码哈希和 Flask secret：

```bash
bangumi2mal hash-password
bangumi2mal generate-secret
```

将输出分别填入 `WEB_PASSWORD_HASH` 和 `FLASK_SECRET_KEY`。不要给环境变量值额外套引号，除非你的 shell 或部署方式要求。

初始化并检查：

```bash
bangumi2mal init-db
bangumi2mal check-config --web
```

## MAL 授权

可以通过 Web 首页的 “Authorize MAL” 完成授权，也可以使用命令行：

```bash
bangumi2mal auth-mal
```

CLI 会打开授权地址。授权回跳时如果 Web 服务没有运行，浏览器显示无法连接是正常的；复制地址栏中的完整 callback URL，粘贴回 CLI 即可。

token 保存在 `data/app.db`。它不会被 Git 跟踪，但仍应限制该文件和 `.env` 的系统权限：

```bash
chmod 600 .env data/app.db
```

## CLI 同步

先执行 dry-run：

```bash
bangumi2mal check-config --remote
bangumi2mal sync --dry-run
```

确认 `reports/<run-id>/` 中的结果后再真实写入：

```bash
bangumi2mal sync
```

每次运行会生成：

- `synced.csv`：已同步、计划同步和无需变更的条目
- `unresolved.csv`：未能匹配或失败的条目
- `all.csv`：完整结果

CSV 使用 UTF-8 BOM，便于直接用 Excel 打开。

## Web UI

开发或本机运行：

```bash
bangumi2mal serve --host 127.0.0.1 --port 5000
```

打开 `http://127.0.0.1:5000`，输入配置的单一访问密码。Web 中可以：

- 发起 dry-run 或真实同步
- 查看每次运行和字段变化
- 查看模糊匹配候选
- 输入正确 MAL ID，保存映射并重新 dry-run
- 管理已有自动/人工映射

## 自动同步

自动同步默认关闭。至少成功检查一次 dry-run 后，在 `.env` 中设置：

```env
AUTO_SYNC_ENABLED=true
AUTO_SYNC_HOURS=6
```

调度器随 Web 进程启动，并使用同一个同步锁避免任务重叠。开启内置调度器时必须只启动一个 Web worker，否则每个 worker 都会创建自己的调度器。

## Ubuntu 部署

推荐目录为 `/opt/bangumi2mal`，使用一个 Gunicorn worker，由 Nginx 反向代理并终结 HTTPS。

仓库提供：

- `deploy/bangumi2mal.service.example`
- `deploy/nginx.conf.example`

基本步骤：

```bash
sudo useradd --system --home /opt/bangumi2mal --shell /usr/sbin/nologin bangumi2mal
sudo mkdir -p /opt/bangumi2mal/data /opt/bangumi2mal/reports
sudo chown -R bangumi2mal:bangumi2mal /opt/bangumi2mal
```

将项目放入该目录、创建 `.venv`、安装 `.[deploy]`、配置 `.env` 后：

```bash
sudo cp deploy/bangumi2mal.service.example /etc/systemd/system/bangumi2mal.service
sudo systemctl daemon-reload
sudo systemctl enable --now bangumi2mal
```

复制并修改 Nginx 示例，配置域名和 TLS。通过 HTTPS 部署时务必设置：

```env
MAL_REDIRECT_URI=https://你的域名/oauth/mal/callback
SESSION_COOKIE_SECURE=true
```

同时在 MAL API 应用设置中更新为同一个 Redirect URL。

## 数据与备份

- `data/app.db`：OAuth token、已确认映射、同步历史
- `reports/`：每次运行的 CSV
- `.env`：密钥与运行配置

备份这三者即可迁移服务器。SQLite 使用 WAL 模式；在线备份时应使用 SQLite backup 命令或先停止服务。

## 测试

测试不会请求或修改真实 Bangumi/MAL 账号：

```bash
pytest
```

## 安全边界

- Web 只有密码，没有用户名或多用户权限系统。
- 密码仅保存为 Werkzeug 哈希。
- 所有 POST 表单带 CSRF token，并限制连续登录失败。
- OAuth token 不出现在日志、CSV 或页面中。
- SQLite 中的 OAuth token 并未额外加密，因此服务器文件权限和磁盘安全仍然重要。
- 公开互联网部署必须使用 HTTPS。

## License

[MIT](LICENSE)
