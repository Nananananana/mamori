# mamori 守り

**用真实数据调用外部大模型，但不把真实数据发出去。**

English: [README.md](README.md) ／ 日本語: [README.ja.md](README.ja.md)

面前是一封客户邮件，手边是一个几秒钟就能起草回复的模型。于是你把姓名删掉、
重新打一遍，占位方式前后不一致，签名栏里的电话号码漏掉了，最后得到的草稿
还不如自己写。

`mamori` 把这一步接过去，在本地完成，而且前后一致。

```text
你写的                          模型看到的                      你拿回的
─────────────────────────────  ─────────────────────────────  ─────────────────────────────
张伟先生您好                    <PERSON_001>先生您好            张伟先生您好
请拨打 13812345678             请拨打 <PHONE_001>              请拨打 13812345678
```

`<PERSON_001>` 与 `张伟` 之间的对应表，始终留在你自己的机器上。

---

## 安装

```bash
pip install mamori
```

不需要模型，不需要 GPU，不联网。默认检测器是微秒级的模式规则。

## 使用

```python
import mamori

with mamori.PrivacySession() as session:
    protected = session.protect("请联系张伟先生，邮箱 zhang@example.com")
    # -> '请联系<PERSON_001>先生，邮箱 <EMAIL_001>'

    answer = call_your_favourite_llm(protected.protected_text)

    print(session.restore(answer).text)
```

一个 session 就是一段对话。同一个值在整个 session 内始终对应同一个占位符，
因此模型能判断两处提到的是同一个人，第五轮的回复也仍然可以用第一轮的值还原。

### 流式还原

回复是逐 token 到达的，`<PERSON_001>` 会拆成 `<PER` / `SON_0` / `01>` 分批送来。
可以边收边还原：

```python
stream = session.stream_restore()
for chunk in llm_response_stream:
    print(stream.feed(chunk), end="", flush=True)
print(stream.finish())
```

无论怎样分块，输出与把整段回复交给 `restore()` 的结果**完全一致**，
这一点用 Hypothesis 对各种切分位置做了验证。一个「大多数情况下一致」的
流式实现，会在模型恰好选中的那个 token 边界上出错：既不可复现，
也要等到真实数据被弄坏才会被发现。

### 命令行

```bash
mamori inspect -f draft.txt
```

```text
2 detected:
      3:5     PERSON           <PERSON_001>       张*                   (zh, 0.90)
     13:24    PHONE            <PHONE_001>        1**********          (zh, 0.90)
```

最后一列是命中的规则集，可以看出是哪种语言的规则找到的。
`mamori demo` 会跑完整的一次往返，其中包含占位符被改动过的回复，
可以直接看到恢复的效果。

---

## 语言支持

日语、英语、中文，同一篇文档里混排也可以：

```text
田中太郎さんへ                        ->  <PERSON_001>さんへ
CC: Mr. John Smith (Acme Inc.)       ->  CC: Mr. <PERSON_003> (<COMPANY_NAME_002>)
张伟先生，请拨打 13812345678          ->  <PERSON_004>先生，请拨打 <PHONE_003>
```

规则按语言分成语言包，文本给出理由时对应的语言包才会运行。默认全部启用——
文档里出现意料之外的语言，恰恰是没人手工处理过的那一种情况——
在你确知范围时用 `locales=` 收窄：

```python
mamori.PrivacySession(locales=["zh", "en"])
```

```bash
mamori locales
```

```text
  en  English     16 rules  runs on: latin
  ja  Japanese    11 rules  runs on: han, kana
  zh  Chinese     11 rules  runs on: han  (not when: kana)
```

关键在最后一行。中日共用汉字，两份姓氏表会在对方的文本上不断命中，把普通词
变成人名。假名可以判定：假名出现在日语里，中文里绝不出现，所以文本中一旦出现
假名，中文规则就停下。只有汉字时无法判定，两个语言包都运行，宁可多检——
多一个占位符只损失回答质量，漏掉一个名字损失的才是这个库存在的理由。

邮箱、凭据、卡号、内网地址与语言无关，始终运行。新增一种语言只需要一个模块
加一条注册记录，参见 `register_locale`。

---

## 可切换

检测不是固定流程，而是**一串 pass**。每个 pass 同时看到文本
和「此前的 pass 已经找到的东西」。

```text
rules            通用模式 + 适用的语言包
  ↓
co-occurrence    把置信度达标、已被确认的值，
                 在同一段文本的其他出现处也找出来
```

第二个 pass 的必要性在于：**某一句里被敬称确定的人名，
文中其他提及处是同一个人**，但只看那些提及处的规则无从判断。

```text
尊敬的张伟先生：              ← 敬称确定了它
本次评审由张伟主持。           ← 这里没有任何线索
请张伟在周五前回复。           ← 这里也没有
```

三处都会被保护。在中文里这不是优化，而是必需——**没有别的锚点可用**。

所有可切换项集中在一个对象上：

```python
mamori.PrivacySession(
    config=mamori.MamoriConfig(
        locales=["zh", "en"],
        min_confidence=0.7,  # 忽略置信度低的检测：占位符更少，覆盖率也更低
        co_occurrence=True,
    )
)
```

`MamoriConfig` 对文件格式不持任何立场。`from_mapping()` 接收**已经解析好的
映射**，因此用 JSON、TOML、YAML 还是 dict 字面量由调用方决定，
库本身依然没有运行时依赖。

```bash
mamori config                       # 实际生效的设置，以及每一层来自哪里
mamori protect --min-confidence 0.7 -f draft.txt
```

设置按后者优先叠加：默认值 → `--config` → `MAMORI_*` 环境变量 → 命令行参数。
**未知的键会被拒绝而不是忽略**——隐私设置里的拼写错误被默默忽略是最坏的结果：
以为收紧了，其实没有。

### 优先「不漏」

每条规则都声明**层级**。**core** 锚定在几乎不会是别的东西上——校验位、
厂商前缀、敬称、标签。**wide** 只看形状——10 位数字、两个首字母大写的词、
一长串看起来随机的字符。由 stance 决定跑哪些层，**默认是 recall_first**。

| | leak rate | | over-redaction | |
|---|---|---|---|---|
| | balanced | **recall_first** | balanced | **recall_first** |
| `ja-core` | 0.71% | **0.00%** | 0.00% | **3.11%** |
| `en-core` | 2.01% | **0.67%** | 0.66% | **1.44%** |
| `zh-core` | 0.00% | **0.00%** | 2.55% | **4.00%** |

这就是取舍，写出来而不是藏起来。**漏掉是无声且不可挽回的；误报则表现为
「本不该被替换的词被替换了」，是看得见的。** 读保护后文本的人会注意到后者，
但没有人会注意到那个没被替换的人名。

```bash
mamori protect --stance balanced -f draft.txt   # 想减少误报时
mamori eval --stance balanced                   # 两种都能测
```

**stance 不改变任何安全判断。** 什么能发出去由策略决定，
「每个字符只有一个检测胜出」不变，凭据依然被拦截。stance 只改变提出多少候选，
所以「recall_first 绝不会比 balanced 漏得更多」是一条**测试**而不是期望。

wide 规则是 LOW 置信度，因此也可以不改 stance、直接用 `min_confidence` 关掉。

---

## 提示词

涉及两个模型，方向相反；两者的提示词都可读、可改。

**服务端模型**被告知原样保留占位符。这不需要本地模型，立刻就能回本：

```python
system = session.external_system_prompt() + "

" + your_own_system_prompt
```

每一个完好返回的占位符，都是还原过程不必再从改写形式中恢复的一个。

**本地模型**用来找模式覆盖不到的东西：没有任何前置标记的英文人名、中文人名、
看起来像普通词的内部代号。它的提示词里写满了**写正则时积累的知识**。

```bash
mamori prompt detection
```

```text
## What looks sensitive and is not

- Many ordinary words begin with a character that is also a surname. 森林 is a
  forest, not 森 and 林. 原因, 金額, 石油, 田舎 and 林檎 are words.
- This shape is also the shape of ordinary words... 高兴 is 'happy',
  方便 is 'convenient'. Judge from the sentence.
```

因为这些是**关于语言的知识，不是关于正则表达式的知识**。

### 加入公司规则、删掉不合用的

每条 guidance 都有 ID。可以补充库无从知晓的内容，也可以移除不适用的，
**无需 fork**。

```json
{"prompts": {"detection": {
  "disable": ["en.person.unanchored"],
  "add": [{"id": "acme.case", "text": "案件编号形如 ACME-12345。"}]
}}}
```

```bash
mamori prompt detection --guidance   # 列出 ID，可据此 disable
```

**disable 一个不存在的 ID 会被拒绝**，而且是在加载配置时就拒绝，
不会拖到几个月后。

### 接入模型：同一台机器，或内网服务器

现实的部署形态不是笔记本，而是团队共用的一台 GPU 机器：

```json
{"llm": {"model": "qwen2.5:72b", "base_url": "http://llm01.corp:8000/v1/"}}
```

```bash
mamori llm --check     # 在哪里、是否被允许、是否应答
```

```text
  model           qwen2.5:72b
  endpoint        http://llm01.corp:8000/v1/
  host            private (another machine)
  trust boundary  private_network
  reachable       yes
```

同一份配置去掉 `base_url`，用的就是本机模型。其余什么都不用改。

被拒绝的是**公网端点**。检测器拿到的是保护*之前*的文本，
所以位于内网之外的端点不是检测器，而是泄漏本身。这一点会在启动时告知，
而不是等到处理第一份文档时：

```text
REFUSED. This model will not be used:
  'api.openai.com' looks external, which is outside the private_network trust
  boundary.
```

三种边界：`same_host`、`private_network`（默认）、`anywhere`。
写进 `trusted_hosts` 的主机在任何边界下都被允许——
运维人员点名一台主机，本身就是一个判断。
参见 [ADR 0015](docs/adr/0015-a-trust-boundary-not-a-localhost-check.md)。

### 模型和客户端库都可替换

换模型是改一个字段；换*连接方式*是一行代码，而且不给本库增加任何依赖：

```python
from mamori.infrastructure.llm import CallableProvider, register_llm_provider

# 已经加载在同一进程里的模型：任意库，完全不经过 HTTP。
provider = CallableProvider(my_pipeline, name="local-transformers")

# 或者让它可以从配置里按名字选择。
register_llm_provider("vllm", lambda endpoint: MyVLLMProvider(endpoint))
```

```python
from mamori import MamoriConfig
session = MamoriConfig.from_mapping(settings).session()
```

内置 Provider 只用 `urllib` 说 OpenAI 兼容 HTTP，运行时零依赖依然是零。
参见 [ADR 0016](docs/adr/0016-the-model-and-the-client-are-both-replaceable.md)。

无论模型做什么，以下三点都成立：

- **它只能增加。** 即使被说服「什么都不要报告」，结果也只是回到只有规则的状态，
  而那正是此前每个版本的出厂状态。
- **它的输出会与文本核对。** 偏移必须落在范围内，报告的值必须与该区间的字符
  完全一致，否则丢弃。幻觉出来的区间不会被从文档中切走。
- **它的失败不是请求的失败。** 模型缺失、缓慢或损坏，意味着检测器变弱，
  而不是流程停止。用 `require_model` 可以反过来。

API key 不写进配置文件，只写环境变量名（`{"api_key_env": "LLM_API_KEY"}`）。
字面量 `api_key` 会被拒绝。

---

## 三处真正的难点

`mamori` 的大部分工作量，都花在初版实现必然做错的地方。

**模型不会原样把占位符还给你。** `<PERSON_001>` 回来时可能变成 `PERSON_001`、
`<PERSON_1>`、`<person_001>` 或 `＜PERSON_001＞`。还原过程对**书写形式宽容、
对身份严格**：只有当规范化后的 `(类型, 编号)` 确实是本 session 分配过的，
才会替换。其余一律只报告、不解析——回复是不可信输入，
用回复方选定的字符串去查对应表，等于让对方一次一条把表读出去。

**中日文没有词边界，而规范化会让偏移量全部错位。**
`ｔａｎａｋａ＠ｅｘａｍｐｌｅ．ｃｏｍ` 必须和半角写法命中同一条规则，
但替换必须发生在**原始字符串**上，否则用户拿回的是被改写过的文本。
`mamori` 带着字符级偏移表做规范化，规范化坐标下找到的区间可以精确映射回原文。

**检测器之间会冲突，重叠的替换会破坏文本。**
`田中太郎(tanaka@example.com)` 会让三条规则给出互相重叠的区间。
每个字符只能有一个检测胜出，而且规则必须写下来，不能听凭声明顺序：
先取更长的区间，然后是严重度、置信度、起始位置。替换更长的区间同时也会
清除其内部的内容，所以长度排在第一位。

---

## 效果如何

可以直接测：

```bash
mamori eval
```

```text
zh-core  (zh, 25 samples)
  leak rate             0.00%   (0/202 sensitive chars left uncovered)
  over-redaction        4.00%   (11/275 ordinary chars replaced)
  entity P / R / F1   0.844 / 1.000 / 0.915   (match: overlap)
  clean samples       25/25
```

**leak rate** 是标注的敏感字符中没有被任何检测覆盖的比例，也就是
**本会流出去的那一部分**。**over-redaction** 是为此破坏掉的普通文本比例。

**这两个数缺一不可。** 把全文都涂黑，leak rate 完美，回答全毁；
而一个没人愿意继续用的隐私层，实际 leak rate 是 1.0。

实体级 precision / recall 也按类型给出，但不是主指标。
只检出 `田中太郎` 中的 `田中` 时，overlap 匹配算命中，exact 匹配算漏检，
两者都没有说出关键事实：**有两个字的人名发给了第三方。**

质量下限写进了 CI，因此「改好一种语言、悄悄弄坏另一种」的改动会让构建变红。
仅写这套评测集的一小时内就发现了 **5 个真实缺陷**，详见
[ADR 0009](docs/adr/0009-measure-leaked-characters.md)。

之后每一次改动的依据同样是这些数字，而不是判断：

| leak rate | v0.2 | + co-occurrence | + recall_first |
|---|---|---|---|
| `en-core` | 7.37% | 2.01% | **0.67%** |
| `ja-core` | 1.43% | 0.71% | **0.00%** |
| `zh-core` | 1.49% | 0.00% | **0.00%** |

co-occurrence 没有牺牲精确率或 over-redaction。
recall_first 以约五倍的 over-redaction 换来剩下的部分。**两张表必须一起看。**

请把这些数字当作**防止退化的下限，而不是对你的数据的承诺**。
评测集规模小且全为合成数据。25 条编造的句子上 leak rate 为 0，
并不能说明真实文档里的情况。

---

## 做不到的事

这一节请务必读。被高估的安全工具比没有工具更危险，因为它纵容的行为
比它取代的行为风险更高。

- **检测不完整，而且永远不会完整。** 默认规则是正则表达式。
  没有敬称、姓氏又不常见的人名，前面没有任何标记的英文人名，
  缺少省市或街道类型的地址，看起来像普通词的内部代号，
  以及只在上下文中才敏感的信息，都会漏掉。
- **`mamori` 降低泄露概率，但不消除它。** 如果团队原本的规定是
  「不要把客户数据贴进聊天窗口」，`mamori` 不构成修改该规定的理由。
  它是给「还是有人贴了」准备的安全网。
- **它不是合规控制措施。** 本项目未针对 GDPR、HIPAA、个人信息保护法
  或任何其他制度做过评估；在多数制度下，假名化的个人数据仍是个人数据。
- **它保护不了已经被入侵的机器。** 对应表里装的正是你想保护的那些值。
  默认只放在内存里，原因就在这里。
- **它拦不住绕过它的发送。** `mamori` 只在你调用它的地方起作用，
  不经过它的请求无法捕获。

各检测器的具体盲区见 [SECURITY.md](SECURITY.md) 与
[docs/threat-model.md](docs/threat-model.md)（英文）。

---

## 设计

四条原则决定了其余一切。

**外部模型在信任边界之外。** 检测、映射、策略、还原都在本地完成，
且是确定性的。「什么可以发出去」这一判断，绝不依赖你正想要防范的那个服务。

**不把模型当作安全机制。** 后续版本会用本地模型去*发现*候选，这是模型擅长的。
但如何处置候选、如何分配占位符、如何把值放回去，仍然留在可读、可测的代码里。

**Fail-Closed。** 检测器抛出异常则停止；策略拒绝则停止。不返回部分结果——
在调用点上，部分结果与安全结果无法区分。

**凭据是拦截，不是假名化。** 没有任何理由把 API 密钥发给第三方，
哪怕换成占位符，也等于告诉对方「这里有一把密钥」。

```text
interfaces ──> application ──> domain
                    │
infrastructure ──> ports
```

`domain/` 除 Python 标准库外不 import 任何东西。所有与安全相关的判断都在那里，
无需模型、网络或数据库即可测试。

---

## 路线图

`v0.1` 是核心部分：检测、判定、假名化、还原，全部在内存中完成，
可从 Python 或命令行使用。

`v0.2` 加入测量框架与流式还原。`v0.3` 把检测改成 pipeline，
并把所有可切换项集中到一个配置对象上。
`v0.4` 把默认值倒向「不漏」，并搭好了提示词层。
`v0.5` 把模型的所在位置和客户端库都变成配置项，
并把分层从一张图变成一个测试。

| | |
|---|---|
| **v0.6** | OpenAI 兼容的本地代理，现有应用只改 `base_url` 即可接入。 |
| **v0.7** | 用同一套评测集测量模型 pass，并据此调整提示词（而不是凭感觉）。测量所需的一切都已就位。 |
| **v0.8** | Presidio 适配器、可选启用的加密持久化存储。 |
| **v0.9** | 替身值（`张伟` → `王强`）作为策略选项。 |

下一步是代理。没有人会为了采用一个库去重写一个正在运行的应用，
而只能保护新代码的隐私层，能保护的范围非常有限。

语言优先级：**日语与英语为主，中文次之**。中文规则已经实现并纳入测量，
但人名识别有正则表达式在原理上解决不了的部分。相关分析与分阶段方案写在
[ADR 0008](docs/adr/0008-language-packs.md)。

---

## 参与开发

见 [CONTRIBUTING.md](CONTRIBUTING.md)（英文）。最欢迎的贡献是检测规则：
每条规则都是精确率与召回率之间的取舍，
`src/mamori/infrastructure/detectors/` 下的每条规则都写明了倒向哪一边、
以及为什么。

安全问题请参见 [SECURITY.md](SECURITY.md)，不要提交公开 issue。

## 许可证

Apache-2.0，见 [LICENSE](LICENSE)。
