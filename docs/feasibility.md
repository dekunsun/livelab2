# 可行性统计（按场景汇总）

由 `scripts/feasibility.py` 生成，只含汇总数字；标签列用 `Label (common/all)`。

| 指标 | ScenarioA | ScenarioB | ScenarioC | 合计 |
| --- | --- | --- | --- | --- |
| gap_minutes | 426240 | 0 | 0 | 426240 |
| gaps | 10 | 0 | 0 | 10 |
| gaps_10min_plus | 10 | 0 | 0 | 10 |
| rows | 61286 | 4916 | 3326 | 69528 |
| runs_anomalous | 8 | 6 | 3 | 17 |
| runs_normal | 4 | 3 | 4 | 11 |
| steps_label_1 | 6870 | 1174 | 353 | 8397 |
| steps_label_2 | 0 | 0 | 0 | 0 |
| steps_label_3 | 0 | 0 | 0 | 0 |
| unparsed_times | 30236 | 4916 | 3326 | 38478 |
| visible_segments | 0 | 0 | 0 | 0 |
| yaml_anomalies | 14 | 19 | 4 | 37 |
| yaml_begin_unparsed | 14 | 19 | 4 | 37 |
| yaml_category_permanent | 5 | 0 | 0 | 5 |
| yaml_category_transient | 9 | 19 | 4 | 32 |
| yaml_origin_entries_not_structured | 7 | 7 | 3 | 17 |
| yaml_sensor_count_total | 16 | 29 | 2 | 47 |
| yaml_sensors_all_in_csv | 4 | 0 | 1 | 5 |
| yaml_sensors_some_in_csv | 3 | 11 | 0 | 14 |
| yaml_with_sensors | 7 | 11 | 1 | 19 |

运行时长（小时，按每分钟两行估算）：ScenarioA 510.7，ScenarioB 41.0，ScenarioC 27.7

每分钟的行数分布：
- ScenarioA：2 行 × 15525
- ScenarioB：
- ScenarioC：

各标签列出现过的取值：
- ScenarioA · Label (advanced/controller fault)：['0']
- ScenarioA · Label (advanced/hard fault)：['0', '1', '3']
- ScenarioA · Label (advanced/soft fault)：['0']
- ScenarioA · Label (common/all)：['0', '1']
- ScenarioA · Label (common/controller fault)：['0']
- ScenarioA · Label (common/hard and soft)：['0', '1']
- ScenarioA · Label (common/hard fault)：['0', '1']
- ScenarioA · Label (common/soft fault)：['0']
- ScenarioB · Label (advanced/controller fault)：['0']
- ScenarioB · Label (advanced/hard fault)：['0', '0.5', '1', '2', '3']
- ScenarioB · Label (advanced/soft fault)：['0']
- ScenarioB · Label (common/all)：['0', '1']
- ScenarioB · Label (common/controller fault)：['0']
- ScenarioB · Label (common/hard and soft)：['0', '1']
- ScenarioB · Label (common/hard fault)：['0', '1']
- ScenarioB · Label (common/soft fault)：['0']
- ScenarioC · Label (advanced/controller fault)：['0']
- ScenarioC · Label (advanced/hard fault)：['0', '1', '3']
- ScenarioC · Label (advanced/soft fault)：['0']
- ScenarioC · Label (common/all)：['0', '1']
- ScenarioC · Label (common/controller fault)：['0']
- ScenarioC · Label (common/hard and soft)：['0', '1']
- ScenarioC · Label (common/hard fault)：['0', '1']
- ScenarioC · Label (common/soft fault)：['0']

## 结论（2026-10-14，负责人决定前）

**按原设计，连续数据集出不了足够的题。** 原设计用“第一个标签 2”作为“在数据里开始可见”的真值。论文原文（Data Records 一节）写的是：人为诱发的异常用 0 正常、1 已诱发但看不到、2 可见、3 恢复；自然发生的只有 0/1。但数据里的分级标签（`Label (advanced/hard fault)`）按异常片段统计如下（`scripts/phase_patterns.py`）：

| 场景 | 片段的阶段顺序（片段数） | 有“可见”阶段的片段 | 可见阶段 ≥ 10 分钟 |
| --- | --- | --- | --- |
| A | 只有 3：9；只有 1：4 | 0 | 0 |
| B | 只有 3：14；1-2-3：3；0.5-1-2-3：1 | 4 | 1 |
| C | 只有 3：4；只有 1：1 | 0 | 0 |
| 间歇数据集（1.0 用过，Zenodo 17395543） | 2：67；1-2-3：55；2-3：15；1-2：10；只有 1：7；其他：4 | 151 | 38 |

- 连续数据集 37 段异常里只有 4 段（全在 B）有完整的 1→2→3；A 和 C 没有任何 2，和论文的说法对不上。原因未知，需要问作者或读处理脚本。
- B 里的 0.5 很可能来自论文说的“20 秒读数按 30 秒窗口取平均”：标签也被平均了。
- 时间：B、C 和全部 YAML 只有“时:分:秒”，没有日期；A 混了几种日期格式。跨午夜或多日的运行只能按行序重建时间，YAML 的开始/结束时刻在多日运行里有歧义。
- 受影响传感器：37 段里 17 段没写传感器（只有一个字符串），做不了“拿掉传感器”的孪生题；写了的大多是“M101, A101”这样逗号连写，拆开后能对上 CSV 列。
- 间歇数据集按 1 Hz 估算（1.0 预登记写的是 1 Hz），≥ 10 分钟的门槛对应 600 步。

**需要负责人决定的**：主数据源换成间歇数据集，还是保留连续数据集并改真值定义。保留集抽签等这个决定之后再做。
