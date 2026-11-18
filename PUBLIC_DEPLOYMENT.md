# 公网演示部署（独立于本机 Compose）

`compose.public.yaml` 是**单独使用**的部署文件；不要与 `compose.yaml` 叠加。它只向公网发布 Caddy 的 TCP 80/443，SourceLab 的 8765 只在 Compose 网络内部可访问；Caddy 对**所有路径（包括 PDF 与 API）**实施 HTTPS 和 HTTP Basic Auth。本配置未向应用传入模型密钥，默认仅演示无需付费的解析、证据检索和图谱。不能用它替代正式的多用户身份与数据隔离。

## 上线前准备

1. 准备有公网 IPv4/IPv6 的 Linux 服务器、指向该服务器的域名及 Docker Engine/Compose。云防火墙只允许必要的 TCP 80/443、管理用 SSH；**不要对公网放行 8765**。如服务器已有占用 80/443 的服务，先规划同一反向代理或另选服务器。
2. 仅复制 `research_agent_mvp` 源码和有分享权限的示例资料到服务器；不要复制本机 `data/`、`.env`、真实论文或 API Key。本部署文件默认**不挂载**上级 `pdf/` 目录；可从浏览器上传有权分享的测试 PDF。
3. 在服务器上的本目录执行 `cp public.env.example public.env`，设置真实的域名、联系邮箱、评审用户名。用可信的 Caddy 安装或容器执行 `caddy hash-password`，**交互式输入强密码**，把输出的 bcrypt 哈希填入 `public.env` 的 `ACCESS_PASSWORD_HASH`，保持**单引号**以免 `$` 被 Compose 插值。不要把明文密码放入 shell 命令、项目文件或截图；通过私密渠道向评审提供账号。确保 `public.env` 文件权限仅允许管理员读取。
4. 在服务器上执行：

   ```sh
   docker compose --env-file public.env -f compose.public.yaml config --quiet
   docker compose --env-file public.env -f compose.public.yaml up --build -d
   docker compose --env-file public.env -f compose.public.yaml ps
   ```

   对 Caddy 生效的域名证书申请，要求域名 DNS 正确且公网能到达服务器的 80/443；证书申请可能受域名、网络和证书服务状态影响。

## 验收与安全边界

- 从**另一条网络**访问 `https://你的域名/`：未登录应返回 `401`；评审账号登录后 `/api/health` 应返回 `{"status":"ok",...}`；首页及官方允许公开的样例上传、问答证据、图谱应可用。**不要把账号密码填入 `curl -u` 命令或公开录屏**。
- 执行 `docker compose --env-file public.env -f compose.public.yaml ps`，检查应用和网关状态；应用只能有 `8765/tcp`（无宿主端口映射）。检查 `docker compose ... logs --tail=80` 时不要泄露用户上传内容或密钥。
- 重启前后核对演示数据仍在命名卷中。不要用 `down -v`，它会移除持久化卷。
- **本配置并非已部署成功的公网实例**。上云后仍应做 TLS/认证、上传/并发、恢复、日志和异常处理验收。HTTP Basic Auth 是共享门禁，不提供个人账号、数据隔离或审计；评审用户可访问同一实例的所有资料。勿放置私密论文或启用不受预算约束的收费模型 API。
