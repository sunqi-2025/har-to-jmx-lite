# har-to-jmx-lite

[![CI](https://github.com/sunqi-2025/har-to-jmx-lite/actions/workflows/ci.yml/badge.svg)](https://github.com/sunqi-2025/har-to-jmx-lite/actions/workflows/ci.yml)
[![License: MIT](https://img.shields.io/badge/License-MIT-blue.svg)](LICENSE)

[English](README.md) | 简体中文

面向接口测试与性能压测场景的 **零依赖 HAR 转 JMeter 5.6 `.jmx` 脚本与脱敏接口文档工具**——纯 Python 标准库实现，既可独立命令行运行，也按标准 `SKILL.md` 封装为可直接安装的 Agent Skill。

浏览器导出的 `.har` 抓包文件通常混杂大量静态资源、预检 `OPTIONS` 请求以及真实鉴权 Cookie/Token。本工具自动完成静态噪点过滤、REST 路径 ID/UUID 归一化、敏感请求头脱敏与参数化、JMeter 5.6 脚本生成以及静态防泄露校验。

---

## 快速上手

需要 **Python 3.9+**，零第三方依赖：

```bash
# 1. 扫描 HAR 中的唯一业务接口清单
python3 scripts/har_to_jmx_lite.py scan examples/sample_shop_api.har --lang zh

# 2. 生成自动脱敏的中文 Markdown 接口文档
python3 scripts/har_to_jmx_lite.py doc examples/sample_shop_api.har -o api_doc.md --lang zh

# 3. 生成参数化 JMeter 5.6 .jmx 测试计划并立即做静态校验
python3 scripts/har_to_jmx_lite.py jmx examples/sample_shop_api.har -o shop_flow.jmx \
  --threads 10 --ramp-up 5 --loops 2 --validate

# 4. 运行单元测试
python3 -m unittest discover -s tests -v
```

---

## 核心特性

- **自动降噪与路径归一化**：过滤 `.js/.css`/图片/字体及 `OPTIONS` 预检请求，自动将数字 ID 与 UUID 归一化为 `/{id}`、`/{uuid}` 便于去重。
- **鉴权脱敏与环境变量参数化**：Markdown 文档自动隐藏 `Authorization`/`Cookie`/API Key；`.jmx` 自动提取 `${PROTOCOL}`、`${BASE_HOST}`、`${BASE_PORT}` 与 `${AUTH_TOKEN}`。
- **规避 417 报错坑**：留空 `HTTPSampler.implementation` 使用 JMeter 默认 Java HTTP 实现，避免大 POST 请求发 `Expect: 100-continue` 触发反代 `417 Expectation Failed`。
- **静态校验门禁（`--validate`）**：校验 XML 结构完整性并扫描是否残留未参数化的明文 Bearer/JWT Token。

---

## 打包标准 Skill ZIP

```bash
python3 scripts/package_skill.py
# 产出：dist/har-to-jmx-lite.zip
```
