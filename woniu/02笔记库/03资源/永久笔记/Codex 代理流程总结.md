**ssh -N -L 127.0.0.1:7892:127.0.0.1:7892 ubuntu@152.136.161.128**

  公司inode会自动识别clash软件，强制卸载，不做恶意绕开，虚拟注册的操作。毕竟网络口子是公司的，热点和公司wifi来回切换太过费时，况且我一直安装卸载clash，有种一直在给自己做心肺复苏的感觉。绷不住。

正好公网ip还在，做个简单代理，让服务器承担去美国西海岸的职责。

本质代理转发,mihomo 接收 HTTP / HTTPS / SOCKS 代理请求.把请求转发到对应节点
## 构成

```text
Codex 
  -> 本机 127.0.0.1:7892
  -> SSH 隧道
  -> 服务器 127.0.0.1:7892
  -> mihomo
  -> OpenAI / Codex 官方服务
```

## 核心原理

本机只访问 `127.0.0.1:7892`，SSH 隧道把流量转发到服务器上的 `mihomo`。

```powershell
ssh -N -L 127.0.0.1:7892:127.0.0.1:7892 ubuntu@152.136.161.128
```

服务器上的 `mihomo` 只监听本机地址：

```text
127.0.0.1:7892
```

因此服务器不需要开放 `7892` 公网端口，只需要 SSH 可连接。

## 服务器侧

```text
mihomo 服务：mihomo.service
配置文件：/etc/mihomo/config.yaml
节点文件：/etc/mihomo/providers/airport.yaml
监听地址：127.0.0.1:7892
# 查询命令
root@VM-24-12-ubuntu:/etc/mihomo# mihomo
mihomo             mihomo-all         mihomo-openai-now  mihomo-status
```

检查服务：

```bash
systemctl status mihomo
ss -ltnp | grep 7892
```

重启服务：

```bash
sudo systemctl restart mihomo
```

## 本机侧

代理环境变量：

```text
HTTPS_PROXY=http://127.0.0.1:7892
HTTP_PROXY=http://127.0.0.1:7892
NO_PROXY=localhost,127.0.0.1,::1
```

检查本机隧道：

```powershell
Get-NetTCPConnection -LocalPort 7892

启动隧道：
ssh -N -L 127.0.0.1:7892:127.0.0.1:7892 ubuntu@152.136.161.128

计划任务启动隧道：
Start-ScheduledTask -TaskName CodexProxyTunnel
```


## 验证

验证 OpenAI API：

```powershell
curl.exe -I -x http://127.0.0.1:7892 https://api.openai.com/v1/models

正常返回：
HTTP/1.1 401 Unauthorized
```

验证 Codex 后端：

```powershell
curl.exe -I -x http://127.0.0.1:7892 https://chatgpt.com/backend-api/codex/responses

正常返回：
HTTP/1.1 405 Method Not Allowed
```

## 使用流程

```text
1. 确认服务器 mihomo 正常运行
2. 确认本机 7892 隧道正在监听
3. 启动 Codex
```

## 关键结论

```text
Codex 只需要访问本机 127.0.0.1:7892。
SSH 隧道负责转发到服务器。
服务器 mihomo 负责实际代理。
服务器无需开放 7892 公网端口。
```