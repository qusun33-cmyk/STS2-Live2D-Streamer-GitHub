# 发布到 GitHub

项目名称：虚拟女友玩杀戮尖塔2直播

当前本地仓库已经整理成适合上传 GitHub 的结构，并已排除虚拟环境、日志、缓存、临时文件和真实密钥。

## 已发布仓库

```text
https://github.com/qusun33-cmyk/STS2-Live2D-Streamer-GitHub
```

GitHub 仓库 URL 使用英文 slug，项目展示名使用中文：虚拟女友玩杀戮尖塔2直播。

## 如果你要重新推送

```powershell
cd F:\codex\dist\STS2-Live2D-Streamer-GitHub
git push origin main
```

如果 Windows Git 在代理环境下出现 `Connection was reset`，可以临时使用：

```powershell
git -c http.sslbackend=openssl -c http.version=HTTP/1.1 push origin main
```

## 如果你要改成自己的仓库 URL

```powershell
cd F:\codex\dist\STS2-Live2D-Streamer-GitHub
git remote set-url origin <你的仓库URL>
git push -u origin main
```

## 发布前检查

- 不要提交真实 API Key。
- 不要提交 `.venv*`、`logs`、`temp`、缓存和临时音频。
- 其他用户需要自行配置本机游戏路径。
- LLM 厂商 Key 推荐在可视化控制台中填写，不建议硬编码进仓库。

