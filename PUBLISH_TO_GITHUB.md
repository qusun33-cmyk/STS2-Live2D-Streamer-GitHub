# 发布到 GitHub

## 本地仓库状态

这个打包目录已经整理成适合上传 GitHub 的结构：

- 已排除 `.venv*`、`logs`、`temp`、缓存目录
- 已有顶层 `.gitignore`
- 已有顶层 `README.md`
- 已保留源码、启动脚本、控制台和说明文档

## 如果你已经有 GitHub 仓库 URL

在这个目录执行：

```powershell
cd F:\codex\dist\STS2-Live2D-Streamer-GitHub
git remote add origin <你的仓库URL>
git branch -M main
git push -u origin main
```

## 如果你要手动在 GitHub 新建仓库

1. 打开 GitHub，新建一个空仓库。
2. 仓库名可以用：

```text
STS2-Live2D-Streamer
```

3. 不要勾选初始化 README、`.gitignore`、License。
4. 新建后复制仓库 URL。
5. 回到本地执行上面的 `git remote add` / `git push`。

## 如果你想改成自己的提交身份

执行：

```powershell
git config user.name "你的 GitHub 名称"
git config user.email "你的 GitHub 邮箱"
```

然后重新提交即可。
