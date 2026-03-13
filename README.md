# Literature Review Pipeline

自动从 arXiv + Semantic Scholar 抓取论文，打分排序，生成分析报告。

## 文件结构

```
lit_review/
├── pipeline.py           # 主入口，抓取 + 打分 + 分析 + 生成报告
├── graph.py              # 引用关系图生成（交互式 HTML）
├── fetcher.py            # arXiv + Semantic Scholar API 客户端 + 代码/Demo 检测
├── scorer.py             # 打分系统（Relevance > Bonus > Venue > Impact）
├── analyzer.py           # 关键词/作者/方法分类/方法演化分析
├── requirements.txt      # 依赖 (requests, pyyaml)
├── .env                  # S2 API key（自动加载，不用手动传参）
├── README.md
└── searches/
    └── uav_ugv.yaml      # UAV-UGV 搜索配置（已预置）
```

## 安装

```bash
cd lit_review
pip install -r requirements.txt
```

## 使用方法

```bash
# 运行完整搜索（arXiv + Semantic Scholar）
# API key 从 .env 自动加载，无需手动传参
python pipeline.py searches/uav_ugv.yaml

# 只用 arXiv（快，不消耗 S2 额度）
python pipeline.py searches/uav_ugv.yaml --arxiv-only

# 只用 Semantic Scholar（数据更丰富：有引用量、venue）
python pipeline.py searches/uav_ugv.yaml --s2-only

# 手动指定 S2 API key（覆盖 .env）
python pipeline.py searches/uav_ugv.yaml --s2-api-key YOUR_KEY

# 指定输出目录
python pipeline.py searches/uav_ugv.yaml -o output/uav_ugv_v2
```

## 打分系统 (0-100)

以相关性为核心，code/demo 高权重：

| 维度 | 满分 | 说明 |
|------|------|------|
| **Relevance** | 45 | 三级关键词匹配：critical(+8/+4) high(+5/+2) medium(+2/+1)，标题权重 > 摘要 |
| **Bonus** | 30 | +15 有开源代码, +15 有真机实验/Demo |
| **Venue** | 15 | Tier1=15 (ICRA/IROS/RA-L/RSS/CoRL/NeurIPS/ICML/ICLR), Tier2=10, Tier3=5 |
| **Impact** | 10 | 引用量/年龄 的百分位排名 |

设计原则：跟你研究方向无关的顶会论文不会排到前面；有 code + demo 的论文大幅加分。

## 代码/Demo 检测

检测方式（三层）：

1. **摘要 regex** — 在论文摘要中匹配 `github.com`、`code available`、`real-world`、`hardware experiment` 等关键词
2. **arXiv comment 字段** — 很多作者在 comment 里写 "code at github.com/..."
3. **arXiv 页面爬取** — 对有 arXiv ID 的论文，爬取 arXiv 页面全文，提取 GitHub/GitLab 链接和 demo 关键词

局限：如果代码链接只在 PDF 正文/脚注里而不在摘要或 arXiv 页面上，会漏检。

## 输出文件

运行后在 `output/<config_name>/` 下生成：

- **papers.csv** — 所有论文按总分排序，可在 Excel 中筛选
- **papers.json** — 结构化数据，方便程序读取
- **report.md** — Markdown 报告，包含：
  - Top 50 论文（含分数分解：Rel / Bonus / Venue / Impact）
  - 方法分类（折叠式，每个类别下有论文链接 + score + [CODE]/[DEMO] 标签）
    - Reinforcement Learning, Diffusion Models, GNN, Transformer, MPC, Lyapunov, Formation Control, Path Planning, SLAM, Communication, Swarm 等 18 个类别
  - 方法演化时间线（按年份 x 方法 矩阵）
  - Papers with Code（折叠式，含 repo 链接）
  - Papers with Demo（折叠式）
  - 高频关键词（bigram + unigram）
  - Top 作者（论文数 + 平均分）
  - 年份分布（ASCII 柱状图）
  - Venue 分布
- **config_used.yaml** — 本次运行的配置快照，方便复现
- **citation_graph.html** — 交互式论文引用关系图（由 `graph.py` 生成，见下方）

## 引用关系图（Citation Graph）

基于 pipeline 输出的 `papers.json`，查询 Semantic Scholar 获取论文间的引用关系，生成类似 Research Rabbit 的交互式网络图。

### 使用方法

```bash
# 先跑 pipeline 生成 papers.json，再跑 graph.py
python pipeline.py searches/uav_ugv.yaml
python graph.py output/uav_ugv/papers.json

# 自定义：最低分数 30，最多画 100 个节点
python graph.py output/uav_ugv/papers.json --min-score 30 --max-nodes 100

# 指定输出路径
python graph.py output/uav_ugv/papers.json -o output/uav_ugv/my_graph.html
```

生成后直接浏览器打开 `citation_graph.html` 即可。

### 交互功能

- **滚轮缩放**，**拖拽移动**节点和画布
- **悬停节点**：显示论文详情（标题、年份、分数、venue、引用数、论文链接、代码链接）
- **箭头方向**：A → B 表示 A 引用了 B

### 视觉编码

| 元素 | 含义 |
|------|------|
| 节点大小 | 论文得分越高，节点越大 |
| 节点颜色 | 方法类别（RL=红, MPC=蓝, Formation=绿, Path Planning=橙, GNN=深橙, Swarm=粉, Communication=棕, SLAM=青, 等） |
| 金色边框 | 有 Code + Demo |
| 绿色边框 | 仅有 Code |
| 粉色边框 | 仅有 Demo |
| 半透明节点 | 与其他论文无引用关系（孤立节点） |

### 工作原理

1. 读取 `papers.json`，按 `--min-score` 过滤，取前 `--max-nodes` 篇
2. 对每篇论文，通过 S2 API 查询其 `references`（参考文献列表）
3. 检查每条参考文献是否也在我们的论文集中（通过 S2 paper ID 或 ArXiv ID 匹配）
4. 如果 A 的参考文献里有 B，画一条 A → B 的边
5. 用 `pyvis`（基于 vis.js）生成交互式 HTML，使用 ForceAtlas2 力导向布局

需要额外安装：`pip install pyvis networkx`

## 换 Domain

复制 `searches/uav_ugv.yaml`，修改以下部分：

1. **search_queries** — 改关键词和 arXiv 分类，确保每个关键词都锚定你的核心方向
2. **relevance_keywords** — 改 critical/high/medium 三级关键词以匹配新方向的打分重点
3. **venue_tiers** — 如需调整会议/期刊的分级

示例：做 swarm robotics 的 review → 新建 `searches/swarm.yaml`，把关键词改成 swarm 相关即可。

## Semantic Scholar API

当前使用 ai4scholar.net 代理，key 已存在 `.env` 文件中，自动加载。

支持两种 key 格式：
- `sk-user-xxx` → 自动识别为 ai4scholar.net 代理
- 其他格式 → 识别为官方 Semantic Scholar API key

## Pipeline 工作原理

### Step 1: 抓取论文

对 YAML 配置里每个 `search_queries` block 的每个关键词，**同时查两个来源**：

**arXiv API** (`http://export.arxiv.org/api/query`)
- 免费，无需 key
- 把关键词拆成 AND 连接：`"UAV UGV coordination"` → `all:UAV AND all:UGV AND all:coordination`
- 可限定 arXiv 分类（如 `cs.RO`, `cs.MA`），过滤掉物理/数学等无关领域
- 返回 XML (Atom feed)，解析出：标题、摘要、作者、年份、comment（常含 venue 信息）、PDF 链接
- 速率限制：每次请求间隔 3 秒

**Semantic Scholar API** (via ai4scholar.net 代理，兼容官方 S2 API)
- 端点：`https://ai4scholar.net/graph/v1/paper/search`
- 认证：`Authorization: Bearer <key>`
- 直接搜原始关键词字符串，S2 内部做语义匹配（比 arXiv 纯关键词匹配更智能）
- 返回 JSON，**比 arXiv 多**：`citationCount`、`venue`（会议/期刊名）、`openAccessPdf`、`fieldsOfStudy`、`publicationTypes`
- 速率限制：有 key 时 0.5 秒间隔，无 key 时 3 秒

5 个搜索 block × 5-8 个关键词 × 2 个来源 ≈ 1200+ 条原始结果

### Step 1.5: 去重 + 代码/Demo 检测

**去重**：按标题 normalize（去掉空格、标点、大小写）匹配。两个来源命中同一篇论文时，合并元数据（取更高的引用量、更完整的 venue 信息等）。1230 → 712 篇。

**代码检测**（三层）：
1. 摘要 regex：匹配 `github.com`、`gitlab.com`、`code available`、`open source`
2. arXiv comment 字段：很多作者写 "code at github.com/..."
3. arXiv 页面爬取：对有 arXiv ID 的论文，GET `arxiv.org/abs/XXXX`，在 HTML 全文中找 GitHub/GitLab 链接

**Demo 检测**：在摘要/comment/arXiv 页面中匹配关键词：
`real-world`、`real robot`、`hardware experiment`、`physical experiment`、`field test`、`outdoor experiment`、`deployed`、`flight experiment` 等

局限：如果代码/demo 信息只在 PDF 正文脚注里，会漏检。

### Step 2: 打分排序

每篇论文算 4 个子分，加总后降序排列：

| 子分 | 满分 | 算法 |
|------|------|------|
| **Relevance** | 45 | 三级关键词匹配。`critical`（"UAV-UGV"、"aerial-ground"）：标题+8 / 摘要+4。`high`（"UAV"、"coordination"）：标题+5 / 摘要+2。`medium`（"reinforcement learning"、"path planning"）：标题+2 / 摘要+1。封顶 45 |
| **Bonus** | 30 | 有开源代码 +15，有真机实验/Demo +15 |
| **Venue** | 15 | regex 匹配 venue 字段。Tier1（ICRA/IROS/RA-L/RSS/CoRL/NeurIPS/ICML/ICLR/IJRR/T-RO）=15，Tier2（AAMAS/CDC/ICUAS）=10，Tier3（Workshop）=5，arXiv preprint=2 |
| **Impact** | 10 | `引用量 / 论文年龄` 在所有结果中的百分位 × 10 |

### Step 3: 分析

- **高频关键词**：从标题+摘要提取 bigram（二元词组）和 unigram，过滤 stopwords，按频率排序
- **Top 作者**：按论文数量 + 平均论文分数排序
- **方法分类**：18 个预定义类别（RL、Diffusion、GNN、Transformer、MPC、Lyapunov、Formation Control、Path Planning、SLAM、Communication、Swarm 等），每篇论文按摘要关键词归入对应类别
- **方法演化**：按「年份 × 方法关键词」矩阵统计趋势，展示哪些方法在哪些年份增长

### Step 4: 生成报告

输出到 `output/<config_name>/`：
- `papers.csv`：Excel 友好，按总分排序，含分数分解
- `papers.json`：结构化数据
- `report.md`：Markdown 报告（Top 50 表格、折叠式方法分类含论文链接、演化时间线、Code/Demo 列表等）
- `config_used.yaml`：本次运行的配置快照（`yaml.dump` 自动生成，key 按字母排序、无注释，仅供复现用）
