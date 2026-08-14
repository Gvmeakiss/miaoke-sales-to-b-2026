# 销售三单匹配（Miaoke · 2026H1 toB） 🔍

> 对 Miaoke 2026 年 1–6 月 toB 销售订单、发运单与 SAP 发票执行三单匹配，按 OMS / DMS 渠道分别输出总体汇总、公司汇总、AQPP 差异场景、冲销明细与未匹配明细的审计工具。

[![Language](https://img.shields.io/badge/language-Python-blue)](https://github.com/Gvmeakiss/miaoke-sales-to-b-2026) [![License](https://img.shields.io/badge/license-MIT-green)](https://github.com/Gvmeakiss/miaoke-sales-to-b-2026/blob/main/LICENSE) [![Domain](https://img.shields.io/badge/domain-Audit%20Analytics-orange)](https://github.com/Gvmeakiss/miaoke-sales-to-b-2026)

## 📌 项目简介

本仓库对 Miaoke 2026 年 1–6 月 toB 销售三单执行匹配，是 2026H1 生产版本（AQPP 无交货金额模式）。订单/发运取数区间 `2025-12-01` 至 `2026-06-30`，发票期间 `2026-01-01` 至 `2026-06-30`。核心分类为 24 子组 `AQPP-01~24`（金额 `V1–V3` × 数量 `Q1–Q8`），FY25 场景作为兼容与同比字段保留。与 2026H1 妙可仓库相比，本仓库额外具备**冲销前置配对**、**币种/数量单位准入**、**PBC 业务范围拆分**与**OMS 匹配能力诊断**，并配有一组**小样本单元测试**。OMS 与 DMS 先按渠道字段互斥切分再分别匹配。

## ✨ 功能特性

- **双渠道互斥匹配**：`match_oms.py` / `match_dms.py` 按 `platform_order_no` / `external_order_no` / `DMS销售单号` 是否非空切分；主聚合键为「订单号 + 物料号」（OMS 组合键用固定分隔符 `||`）。
- **AQPP 无交货金额模式**：`aqpp_scenarios.classify_value` / `classify_quantity` / `assign_aqpp_scenarios` 交叉得到 `AQPP-01~24`；`map_aqpp_to_legacy` 反向映射 FY25 场景。
- **not test 单据存在性编码**：`aqpp_scenarios._not_test_code` 产出 `NT-00`、`NT-28` 至 `NT-33`。
- **冲销前置处理**：`cancellation_preprocessing.preprocess_cancellations` 按 SAP 原发票引用配对（`config.CANCELLATION_ORIGINAL_TYPE_MAP`），区分全额/部分/跨期/待确认冲销（CA-01~CA-06），仅安全的部分冲销按剩余净额进入 AQPP；`aggregate_cancellation_registry` 汇总已冲销业务键。
- **严格容差与浮点保护**：`tolerance_utils` 是唯一判断实现——`equal_with_tolerance` / `greater_with_tolerance` / `absolute_less_than` / `scalar_is_zero`，以 `FLOAT_BOUNDARY_EPSILON = 1e-9` 消除 `10.02-10.00` 类二进制误差；恰落 `±0.02` 边界的关系不唯—分类，进入 `NT-00`。
- **币种/单位准入**：`config.BASE_CURRENCY='CNY'`、`ASSUME_BASE_CURRENCY_WHEN_ORDER_MISSING`、`ASSUME_BASIC_QUANTITY_UNIT`、`AQPP_ALLOWED_CURRENCY_STATUSES`/`AQPP_ALLOWED_UNIT_STATUSES` 集中管理订单/发运缺币种、单位时的明确准入假设。
- **发票类型政策集中管理**：`config.INVOICE_TYPE_RULES`（ZA01 标准、ZA03/04/05 贸易类正常参与、ZA07/ZB01 特殊场景参与、ZB02 退货、ZB05/06 借贷项、ZQ01–ZQ10 冲销配对等），未知类型默认待确认。
- **PBC 业务范围拆分**：`split_invoice_by_scope_and_type.classify_invoice_scope` 按 `config.PBC_INVOICE_SCOPE_TYPES` 将原始发票归入 ToB-DMS / ToB-OMS / To C / 其他，仅复现匹配前渠道归属，不应用 AQPP 政策或冲销净额化。
- **OMS 匹配能力诊断**：`invoice_matchability.build_oms_invoice_type_matchability` 输出各发票类型的匹配键完整性、订单/发运命中与三单齐全率。
- **FY25 兼容汇总**：`legacy_summary.build_fy25_format_summary` 用 FY25 场景映射生成去年版式汇总并补齐 `NT-00/28~33`。
- **预处理与校验**：`preprocess_2026.py` 读取 SQL/发票 Excel 生成三份标准化 PKL；`validate_2026.py` 校验字段契约、渠道数据量与单号覆盖；`data_standardization.py` / `pipeline_common.py` 提供共用标准化与字段契约；`archive_release.py` 生成轻量归档、文件清单与 SHA256 校验值。
- **小样本单元测试**：`test_aqpp_scenarios.py`、`test_cancellation_preprocessing.py`、`test_export_utils.py`、`test_invoice_aggregation.py`、`test_invoice_matchability.py`、`test_invoice_scope_split.py`、`test_legacy_summary.py`，覆盖 24 组、±0.02 边界、币种/单位准入、冲销与完整 NT 范围，不读取全量数据。

## 📂 目录结构

```
miaoke-sales-to-b-2026/
├── README.md
├── config.py                     # 路径、期间、ORDER_STATUS_EXCLUDE、INVOICE_TYPE_RULES、
│                                 #   PBC_INVOICE_SCOPE_TYPES、CANCELLATION_ORIGINAL_TYPE_MAP、
│                                 #   AMOUNT/QUANTITY_TOLERANCE、FLOAT_BOUNDARY_EPSILON、币种/单位准入
├── launch_all.py                 # 一键预处理 + OMS/DMS 匹配（--rebuild / --preprocess-only）
├── preprocess_2026.py            # 读取 SQL/发票 Excel → 三份标准化 PKL
├── validate_2026.py              # 校验 PKL 字段、渠道数据量、单号覆盖
├── data_standardization.py       # 单号/数值/币种/数量单位标准化
├── tolerance_utils.py            # 严格容差与浮点保护带唯一实现
├── pipeline_common.py            # OMS/DMS 共用读取、字段契约、状态与年度筛选
├── invoice_type_policy.py        # 识别发票类型并判断是否参与匹配
├── invoice_matchability.py       # OMS 各发票类型匹配能力诊断
├── cancellation_preprocessing.py # 冲销配对、剩余净额与已冲销业务键注册
├── match_oms.py                  # OMS 匹配、聚合、分类与导出
├── match_dms.py                  # DMS 匹配、聚合、分类与导出
├── reconciliation_measures.py    # build_three_way_measures 统一 SIV/SOV/SIQ/SOQ/GDNQ 口径
├── aqpp_scenarios.py             # AQPP-01~24、NT 分类与 FY25 映射
├── scenario_utils.py             # FY25 原逻辑及新旧场景并行校验
├── legacy_summary.py             # FY25 版式兼容汇总（build_fy25_format_summary）
├── export_utils.py               # 汇总、公司、分场景与未匹配输出
├── export_schema.py              # 审计字段顺序、中文字段名与冗余字段隐藏
├── export_order_delivery_excel.py# 订单/发运 PKL → Excel，超行分卷
├── split_invoice_by_type.py      # 原始发票 PKL 按类型拆分 Excel
├── split_invoice_by_scope_and_type.py # 按 PBC 范围 + 类型拆分并生成核对表
├── archive_release.py            # 生成轻量归档、清单与 SHA256
├── requirements.txt              # pandas>=3.0 / numpy>=2.0 / openpyxl>=3.1 / XlsxWriter>=3.2
├── test_*.py                     # 小样本单元测试（见功能特性）
└── LICENSE
```

## 🔧 环境要求

- Python 3.11+（README 建议；PKL 由 pandas 3.x 生成，归档环境须 `pandas>=3.0` 以免旧版无法反序列化字符串类型）
- 依赖见 `requirements.txt`：`pandas>=3.0`、`numpy>=2.0`、`openpyxl>=3.1`、`XlsxWriter>=3.2`

## 🚀 安装

```bash
git clone https://github.com/Gvmeakiss/miaoke-sales-to-b-2026.git
cd miaoke-sales-to-b-2026
python3 -m pip install -r requirements.txt
```

## 💡 快速开始 / 使用示例

生产入口为 `launch_all.py`：

```bash
# 复用已有 PKL，执行 OMS + DMS 匹配
python3 launch_all.py

# 原始输入更新或预处理规则变化时，重建 PKL 后匹配
python3 launch_all.py --rebuild

# 只做预处理，不执行匹配
python3 launch_all.py --preprocess-only

# 单独校验 PKL、单独跑渠道匹配
python3 validate_2026.py
python3 match_oms.py
python3 match_dms.py

# 运行全部小样本单元测试（不读取全量数据、不生成 Excel）
python3 -m unittest discover -p 'test_*.py' -v

# 原始清单导出与发票拆分
python3 export_order_delivery_excel.py --max-rows 1000000
python3 split_invoice_by_type.py
python3 split_invoice_by_scope_and_type.py

# 生成轻量归档与文件清单
python3 archive_release.py --version 2026H1_20260728_v1
```

匹配脚本会覆盖同名 Excel；PKL 默认复用，仅 `--rebuild` 或 `preprocess_2026.py --force` 才重建。

## 🧠 核心逻辑（方法论）

1. **预处理标准化**：`preprocess_2026.py` 读取订单/发运 SQL 与月度发票 Excel，经 `data_standardization.py` 标准化后写出三份 PKL（`config.ORDER_PKL` / `DELIVERY_PKL` / `INVOICE_PKL`）；`validate_2026.py` 校验必需字段、渠道数据量与 `document_no ↔ OMS出库单号` 覆盖。
2. **渠道切分**：`match_oms.py` / `match_dms.py` 在 `pipeline_common.py` 字段契约下按 `platform_order_no` / `external_order_no` / `DMS销售单号` 互斥切分；剔除 `ORDER_STATUS_EXCLUDE = ['OBSOLETE','CANCEL']`。
3. **发票类型与冲销治理**：`invoice_type_policy` 按 `config.INVOICE_TYPE_RULES` 决定参与/特殊/待确认；`cancellation_preprocessing.preprocess_cancellations` 按 `CANCELLATION_ORIGINAL_TYPE_MAP` 配对冲销，仅安全的部分冲销按剩余净额进入 AQPP，已冲销业务键被注册以分流订单/发运。
4. **统一口径与聚合**：`reconciliation_measures.build_three_way_measures` 生成 `SIV/SOV/SIQ/SOQ/GDNQ`；以可参与匹配的发票聚合结果为主表连接发运与订单。
5. **AQPP 分类**：`aqpp_scenarios.assign_aqpp_scenarios`（内置 `classify_value`、`classify_quantity`）按 `AMOUNT_TOLERANCE=0.02`、`QUANTITY_TOLERANCE=0.02`，容差判断统一经 `tolerance_utils`（带 `FLOAT_BOUNDARY_EPSILON`），得 `AQPP-01~24`；不满足三单齐全或币种/单位准入者归 `NT-00/28–33`；`map_aqpp_to_legacy` 映射 FY25 场景。
6. **诊断与导出**：`invoice_matchability.build_oms_invoice_type_matchability` 输出 OMS 匹配能力页；`legacy_summary.build_fy25_format_summary` 生成去年版式汇总；`export_utils` + `export_schema` 输出总体/公司/场景汇总、AQPP 明细与「其他未匹配」明细（含冲销明细）。程序仅归类，不自动下错报结论。

## 📋 输入与输出

- **输入**：`config.INPUT_DIR` 下订单/发运 SQL（`订单清单：25.12.01-26.06.30.sql`、`发运单清单：25.12.01-26.06.30.sql`）与发票目录（`发票清单：26.01.01-26.06.30/`），仅读取不修改。
- **中间数据**：`config.PKL_DIR`（`pkl/2026H1/`）三份标准化 PKL，由 `preprocess_2026.py` 生成、匹配阶段复用。
- **输出**（`config.OUTPUT_DIR` = `output/2026H1/`，OMS 与 DMS 各多份）：
  - `…汇总.xlsx`：含 `汇总`、`AQPP场景汇总`、`去年格式汇总`、`发票类型汇总`、`OMS类型匹配能力`、`PBC-AQPP桥接`、`冲销处理汇总` 等 Sheet；
  - `…明细.xlsx`：按 AQPP 大类拆 `完全匹配`/`金额差异`/`数量差异`/`数量+金额差异`；
  - `…明细-其他未匹配.xlsx`：`Not Test`、`仅订单`、`仅发货单`、`仅发票`、`已冲销净额0`、`冲销业务待确认`、`特殊发票明细`、`冲销配对明细`；
  - `原始发票清单按类型拆分/`、`发票清单按匹配范围及类型拆分/`（超 `1,048,575` 行自动分卷并生成清单 CSV）。

## ⚙️ 配置说明

集中在 `config.py`：

- 路径：`ORDER_SQL` / `DELIVERY_SQL` / `INVOICE_DIR`、`OUTPUT_PREFIX`、`TARGET_YEAR`、`*_PKL`；
- `ORDER_STATUS_EXCLUDE = ['OBSOLETE','CANCEL']`；
- `INVOICE_TYPE_RULES`：每种发票类型的业务含义、是否参与匹配、是否特殊业务；
- `PBC_INVOICE_SCOPE_TYPES`：原始 PBC 业务范围拆分（ToB-OMS / ToC / 其他），不控制 AQPP 参与政策；
- `CANCELLATION_ORIGINAL_TYPE_MAP` / `CANCELLATION_INVOICE_TYPES` / `CANCELLATION_PROCESSING_ENABLED`：冲销配对规则；
- `AMOUNT_TOLERANCE = 0.02`、`QUANTITY_TOLERANCE = 0.02`、`AMOUNT_TAIL_TOLERANCE = 1.0`、`FLOAT_BOUNDARY_EPSILON = 1e-9`；
- `BASE_CURRENCY='CNY'`、`ASSUME_BASE_CURRENCY_WHEN_ORDER_MISSING`、`ASSUME_BASIC_QUANTITY_UNIT`、`AQPP_ALLOWED_CURRENCY_STATUSES` / `AQPP_ALLOWED_UNIT_STATUSES`。

所有 AQPP/场景判断引用上述集中容差，主流程禁止散落硬编码阈值或直接浮点相等比较；容差判断一律走 `tolerance_utils`。新增发票类型须同时明确「业务含义 / 是否参与 / 是否特殊业务」，未知类型默认待确认。

## ⚠️ 注意事项

- 数据脱敏：仓库不含真实客户业务数据，示例与说明均为脱敏/合成数据；实际运行需将客户导出文件放入 `input/`。
- 口径说明：匹配总体、渠道切分、发票类型政策、冲销与容差以 `config.py` 与代码为准，本 README 仅作说明。
- 三层金额范围：原始发票清单金额 / 参与匹配发票金额 / AQPP 金额三层范围，占比分母各不相同，差异应可由「不参与匹配的发票类型」「关键匹配键缺失」或聚合口径解释，不静默丢弃。
- 审计结论：程序不自动下错报结论，仅按 AQPP/FY25 规则与冲销前置规则输出差异，应对措施由项目组人工选择。

## 🔗 相关仓库

- https://github.com/Gvmeakiss/sales-three-match-miaoke-2026
- https://github.com/Gvmeakiss/miaoke-sales-to-b-2025
- https://github.com/Gvmeakiss/miaoke-sales-to-c
- https://github.com/Gvmeakiss/sales-three-match-newhope-2026

## 📄 License

MIT（详见仓库 `LICENSE`）。

---

<div align="center">

*Disclaimer: Personal project and personal views. Not affiliated with or endorsed by KPMG or any client.*<br>
*本仓库为个人项目与个人观点，与任何前/现雇主及客户无关。*

</div>
