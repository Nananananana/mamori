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


| | |
|---|---|
| **[先跑起来看看](#先跑起来看看)** | 五个场景，外加一次对真实模型的往返 |
| [安装](#安装) · [使用](#使用) | 库、流式还原、命令行 |
| **[不改动你的应用](#不改动你的应用)** | 代理：只改 `base_url`，其余不动 |
| [语言支持](#语言支持) | 中文、日文、英文，同一份文档里混排也行 |
| [可切换](#可切换) | 配置，以及召回率旋钮 |
| [当它判断错的时候](#当它判断错的时候) | 订正——最终决定权在你 |
| [用可读的值](#用可读的值代替占位符) | 替身值，以及它默认关闭的原因 |
| [为什么这个被替换了？](#为什么这个被替换了那个为什么没有) | 以及那个为什么**没有** |
| **[我的数据被怎么处理了？](#我的数据到底被怎么处理了)** | 从你自己的配置算出答案 |
| [接入模型](#接入模型同一台机器或内网服务器) | 同一台机器，或内网服务器 |
| [提示词](#提示词) · [三处难点](#三处真正的难点) | 告诉模型什么，以及难在哪里 |
| **[效果如何](#效果如何)** | 两种尺度下的实测数字 |
| [做不到的事](#做不到的事) · [设计](#设计) · [路线图](#路线图) | 边界，以及接下来 |

---

## 先跑起来看看

不需要任何配置：

```bash
pip install git+https://github.com/Nananananana/mamori.git
mamori demo
```

五个简短的场景，每个回答一个真实会被问到的问题：模型看到的是什么、
你能不能拿回自己的原话；占位符在流式输出里被切开时会怎样；
这一套在文档上还成立吗，而不只是在一句话上；判断错了怎么办；
文本里有密码时会发生什么。

然后用你自己的内容试：

```bash
mamori demo --file draft.txt
mamori demo --scenario roundtrip --text "请拨打 13812345678 联系张伟"
```

```text
you wrote
  Dear Jane Doe, reach me at jane.doe@example.com

the model sees
  Dear <PERSON_001>, reach me at <EMAIL_001>

replaced 2 value(s), and what found each one:
  <PERSON_001>        PERSON        en          0.90
  <EMAIL_001>         EMAIL         universal   1.00
```

右边两列是「哪套规则命中的」和「有多确信」，
所以「这个为什么被打码了」是有答案的。

### 对着真实模型

`--live` 会保护你的文本、真的发给你指定的模型、再把答案还原回来——
整个往返，没有任何模拟：

```bash
mamori demo --live --model llama3.1:8b --api http://localhost:11434/v1/ \
  --text "尊敬的张伟先生，请拨打 13812345678 与我们联系。请用三行概括。"
```

```text
what actually goes over the wire
  尊敬的<PERSON_001>先生，请拨打 <PHONE_001> 与我们联系。请用三行概括。

what the model said (placeholders intact)
  <PERSON_001>先生您好，我们会尽快与您联系。

restored into your own words
  张伟先生您好，我们会尽快与您联系。
```

任何 OpenAI 兼容端点都可以（Ollama、vLLM、LM Studio，
或者用 `--api-key-env` 接托管 API）。

---

## 安装

**尚未发布到 PyPI。** 从仓库安装：

```bash
pip install git+https://github.com/Nananananana/mamori.git
```

这一节写了二十五个版本的 `pip install mamori`，而它**从来没有成功过**：
PyPI 上没有这个名字的包，本项目也从未有过发布它的任务。一个依赖
`mamori>=0.14` 的兄弟项目，其 CI 步骤根本装不上它，却被 `continue-on-error`
包着，于是它本该覆盖的接缝一次都没跑过，也从未变红。**发现它的不是读的人，
是试的人。**

发布都打了标签，也可以指定版本：

```bash
pip install git+https://github.com/Nananananana/mamori.git@v0.25.0
```

不需要模型，不需要 GPU，不联网。默认检测器是微秒级的模式规则。

---

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

## 不改动你的应用

没有人会为了采用一个库去重写一个正在运行的应用。
只要你的应用已经在调用 OpenAI 兼容 API，把 mamori 放在前面，改一个字符串即可。

```bash
mamori serve --upstream https://api.openai.com/v1/
```

```text
mamori proxy on http://127.0.0.1:8100/v1/
  upstream        https://api.openai.com/v1/
  detection       all locales, recall_first
  briefing        prepended
```

把应用指向 `http://127.0.0.1:8100/v1/`，其余什么都不用改。
每条消息在发出前被保护，回复在返回时被还原。
代理会记录它替换了什么，但**从不记录值本身**：

```text
  1 message(s), replaced EMAILx1, PERSONx1, PHONEx1
```

流式也支持：被切成 `<PER`、`SON_0`、`01>` 的占位符会被暂存并还原。
如果消息里有凭据，请求会被拦下而不是转发出去。
默认只监听本机——任何能连到这个端口的人都能把文档送进去。
参见 [ADR 0018](docs/adr/0018-a-proxy-on-the-standard-library.md)。

### 第二轮

默认情况下，代理在两次请求之间不保留任何东西：一次作用域，用一次，随回复一起
清除。对多数客户端而言这不可见，因为它们每轮都重发整个会话，相同的值会落到
相同的占位符上——这个论断从 0.16 起**是一个测试，而不再是一段话**。

它对另一类客户端不成立：历史保存在服务端，每轮只发新消息。服务端回答的是
`<PERSON_001>`，而本进程从未见过 `<PERSON_001>`，于是一个令牌被打印给了人看。

```bash
mamori serve --conversations --upstream https://api.openai.com/v1/
```

回复会带上 `X-Mamori-Session`。回传它的客户端跨轮保持占位符；不回传的客户端
照旧每次获得新的作用域。**令牌由服务器签发，绝不从调用方接受**——它背后是一张
真实值的表，而外人能猜到的标识符就是读别人这张表的办法。无法识别的令牌不会
报错说无法识别，而是安静地开始一段新会话。

会话闲置 30 分钟后失效，最多同时保留 64 个；两个上限都会清除所丢弃的内容，
并且什么都不写入磁盘。看它实际运行：

```bash
mamori demo --scenario conversation
```

参见 [ADR 0028](docs/adr/0028-the-server-names-the-conversation.md)。

---

## 没有人打出来的提示词

提示词正越来越多地不是被写出来的，而是被**组装**出来的——检索层从笔记里挑出
段落，把每段的来源放进头部，再渲染成一份文档。一份文档里有三种东西，它们
并不是同一类：

```text
[fbd4c2a631fd] /home/p.doe/notes/meeting-log.md (Meeting)[464:562]
Met with Priya Raman from Northwind Ltd on Tuesday.
```

```text
[fbd4c2a631fd] /home/<PERSON_001>/notes/meeting-log.md (Meeting)[464:562]
Met with <PERSON_002> from <COMPANY_NAME_001> on Tuesday.
```

**头部点名了一个人。** 家目录标识其所有者，和签名档一样确切，而那个名字往往
在正文里根本不出现。只替换这一段：路径的其余部分是来历，下游可能正在校验它。
系统账号——`runner`、`Public`、`www-data`——由一份封闭清单排除。

**结构不动。** `[fbd4c2a631fd]`、`[464:562]`、`//fileserver/team/`。多涂掉一个
词，代价是回答质量；**多涂掉一个哈希，这份包的 ID 就不再校验**——从下游看，
这和被人篡改过没有区别。在自带数据集里它们被标注为普通文本，所以那里出现任何
替换都会让测试失败。

**引用会原样回来。** 如果有东西在拿模型的引用和发送内容做核对，那么还原必须
逐字一致：差一个字，读起来就是「捏造的引用」而不是「被涂掉的引用」。生成的
300 条回答，300 条完全一致。

```python
result = session.protect(package)
result.reversible      # 只要有内容被掩码，就是 False
result.masked_types    # ('PHONE',) —— 只有类型，永远不含值
```

在文本里，`<PERSON_001>` 和 `[REDACTED]` 看起来同样是「被替换了」，但只有
一个能还原。对核验主张的一方来说，这是 *unsupported*（无支撑）与
*unverifiable*（无法核验）的区别。

```bash
mamori demo --scenario package
```

这个形状是对着 [tsumugi](https://github.com/Nananananana/tsumugi) 测量的——它
渲染的正是这种结构，并在之后核对引用。两个项目互不依赖。参见
[ADR 0029](docs/adr/0029-a-prompt-nobody-typed.md)

---

## 智能体，而不是聊天

当一个应用变成智能体，大部分个人信息就离开了散文，跑进了工具调用的参数里：

```json
{"to": "jane.doe@example.com", "employee_id": "E-45033",
 "body": "Dear Jane Doe, call 415-555-0198."}
```

一次调用，四个值。`mamori serve` 会保护全部，并在模型回调工具时把它们放回去：

```json
{"to": "<EMAIL_001>", "employee_id": "<EMPLOYEE_ID_001>",
 "body": "Dear <PERSON_002>, call <PHONE_001>."}
```

**在载荷里，标签就是键名。** `"employee_id"` 说明值是什么，和句子里的
`工号：` 一样明确——而且周围没有散文，规则没有第二次机会。共读取七类键名，
覆盖英文、日文和中文写法。但**刻意不包含**裸的 `"name"`：在 JSON 里它是工具名的
概率远高于人名，涂掉智能体正要调用的函数名，坏掉的是这次调用。

**结构是负例。** `send_email`、`call_0042`、JSON 结构、enum——一律不动，并由测试
固定。如果保护之后参数不再能被解析，这次请求会被**拒绝**而不是转发出去：泄漏是看得
见的，而三小时后在别人进程里炸掉的载荷是看不见的。

**而且能还原。** 用工具调用而不是句子来回答的模型，其参数同样会被还原——流式传输
时也一样，每个调用都是各自独立的一段文字。没有这一步，应用就会给 `<EMAIL_001>`
发邮件，那种失败看起来像缺陷，而不像泄漏。

```bash
mamori demo --scenario agent
```

`v0.18` 还修了另一个问题：**只要出现一个假名，整份文档的中文规则就会停用**，
于是「主题是日文、正文是中文」的载荷会把正文原样发出去。关于文字体系的证据，
现在只延伸到它所在那句话的末尾。参见
[ADR 0030](docs/adr/0030-a-tool-call-is-text.md)

---

## 投入部署之前

在靠近生产环境之前，团队需要三样东西，而它们都不是检测规则。

### 在提交之前

通过**代码仓库**到达模型的值，从来没有经过这个库。一份写着真实地址的提示词模板、
一份从工单里做出来的测试夹具、一个输出单元格里还留着查询内容的笔记本。

```bash
mamori lint
```

```text
prompts/renewal.md:14: PERSON (0.90, en) J*******
prompts/renewal.md:14: EMAIL (1.00, universal) j**********@e******.com
fixtures/ticket.json:3: PHONE (0.90, en) 4***********

3 finding(s) in 2 file(s); 0 credential(s).
```

**它从不打印值。** 这些输出会落进 CI 日志——日志会被归档、可被检索，而且往往比
仓库本身被更多人读到。

**遇到凭据才失败，其余只报告。** 泄漏一把密钥是事故；夹具里有客户姓名，是应该由
人有意做出的决定。两种情况都让构建失败的检查器，只会教会大家用 `--no-verify`。
为已经做了相反决定的仓库准备了 `--fail-on any`。

把它对准本仓库自己的文档，第一次运行就找出一个缺陷：GitHub 的 URL，正好是一长串
和 base64 密钥完全相同的字符。

### 当你宁愿被拦下

默认情况下，拿不准会倒向「发出去」：低于 `min_confidence` 的检测被丢弃，文本带着
值离开。为法务、医疗，以及一切**泄漏代价无法用回答质量衡量**的场合：

```python
MamoriConfig(min_confidence=0.85, uncertain="refuse")
```

```text
PolicyViolationError: 1 detection(s) below the confidence threshold and this
policy refuses rather than discards them (closest 0.50); nothing sent
```

只有类型和置信度，绝不含值。在默认的 `min_confidence=0.0` 下它什么也不做——因为
没有东西低于零。这两个设置是同一个旋钮：一个说确定性在哪里到头，另一个说到头之后
怎么办。

### 不会被当成标签的占位符

HTML 文档里的 `<PERSON_001>` 是一个未知元素：浏览器会把它丢掉，而被要求编辑这份
文档的模型，看到的是一个标签而不是一个记号。

```python
MamoriConfig(placeholder_style="square")   # [PERSON_001]
```

无论这个设置是什么，还原都接受所有形式，所以用一种风格保护的文档，可以在配置为
另一种风格的会话里还原。占位符的身份是 `(类型, 序号)`，括号只是表面。

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
| `ja-core` | 0.68% | **0.00%** | 0.62% | **2.78%** |
| `en-core` | 1.93% | **0.64%** | 0.00% | **0.72%** |
| `zh-core` | 0.00% | **0.00%** | 1.63% | **2.94%** |
| `ja-docs` | 0.33% | **0.33%** | 0.18% | **1.06%** |
| `en-docs` | 20.02% | **3.50%** | 0.03% | **0.90%** |
| `zh-docs` | 2.37% | **2.37%** | 0.40% | **1.20%** |
| `ja-context` | 0.00% | **0.00%** | 0.00% | **0.00%** |
| `en-context` | 46.85% | **6.31%** | 0.00% | **0.92%** |
| `zh-context` | 0.00% | **0.00%** | 0.00% | **0.53%** |
| `ja-agent` | 0.00% | **0.00%** | 0.00% | **0.00%** |
| `en-agent` | 0.00% | **0.00%** | 0.00% | **0.00%** |
| `zh-agent` | 0.00% | **0.00%** | 0.00% | **0.00%** |

要看的是 `-docs` 那几行：那是按实际发送长度写的业务文档，
而 `-core` 只是中位数 44 个字符的句子片段。
本项目在 `v0.9` 之前公开的所有数字，都只来自后者。

**`en-docs` 在 balanced 立场下泄漏 20.29%**——五分之一的敏感字符——
因为文档里到处是没有任何锚点的人名：出席名单里、署名下面、「报告者:」后面。
这是 recall_first 作为默认值最有力的理由，
也是「在用自己的文本测过之前不要关掉它」最有力的理由。
参见 [ADR 0025](docs/adr/0025-measure-at-the-length-people-send.md)。

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

## 当它判断错的时候

它会错。称呼语这个锚点对的次数远多于错的次数，而 `Dear Monday,` 就是错的那次。
说出来就行：

```bash
mamori correct Monday --never --note "a weekday, not a name"
mamori correct Acme   --always COMPANY_NAME --note "trading name, no suffix"
```

后者补上了从 `v0.1` 起就记录在案的一个缺口——没有法人后缀的商号。
正则通用地够不到它，但**对你自己的数据，运维人员可以直接拍板。**

日志只追加，对某个值最后一次的判断生效；撤销就是再追加一条相反的判断，
什么都不会被删除。规则不会被改写，提示词也不会被改动；
把日志去掉，行为就完全回到从前。

```bash
mamori corrections     # 判断过什么，以及代价是什么
```

**`--never` 是 mamori 里唯一会「减少保护」的操作**，所以把它限制得很窄。
每一条排除都会被 `mamori privacy` 点名，并作为警告让退出码非零，
方便在部署检查里直接失败。而且**凭据永远不能被排除**：

```text
error: that value looks like a credential (API_KEY), and a credential cannot
be ruled 'never'. Nothing was written -- recording it would have put the
credential in a file on disk. Rotate it instead.
```

这个拒绝发生在**写入之前**，由三处独立的检查把守。
参见 [ADR 0024](docs/adr/0024-corrections-are-appended-applied-at-read.md)。

---

## 用可读的值代替占位符

有些模型面对满页的 `<PERSON_001>` 会明显推理不好。换成可读的值，
通常能得到更好的回答：

```json
{"surrogates": ["PERSON", "EMAIL", "PHONE"]}
```

```text
你写的    尊敬的张伟先生，请拨打 13812345678 与我们联系。
发出的    尊敬的林小舟先生，请拨打 138-0013-8000 与我们联系。
还原后    尊敬的张伟先生，请拨打 13812345678 与我们联系。
```

邮箱和号码取自专门保留给文档用途的范围（RFC 2606、未分配号段），
所以就算漏出去，它在任何地方都没有意义。
**但没有任何标准为人名保留过一组名字**，这是留下来的风险。

它**默认关闭**，开启之前值得先理解原因：
没被还原的 `<PERSON_001>` 一眼就能看出来；
没被还原的 `林小舟` 是一句关于另一个人的通顺句子，没人会发现。
占位符可以靠形状识别，所以模型把它写歪了还能还原；
替身值只是一个名字，要么对上，要么对不上。

mamori 能做的是**告诉你**。`RestorationResult.missing` 会列出没能还原的东西
（每次回答都应该检查），而 `mamori privacy` 在替身值开启时一定会告警，
并说明哪些池是保留范围、哪些只是编出来的。

```bash
mamori demo --scenario surrogates
```

参见 [ADR 0026](docs/adr/0026-surrogates-trade-obviousness-for-readability.md)。

---

## 为什么这个被替换了？那个为什么没有？

```bash
mamori trace "Dear Monday, the contract is with Globex Corporation."
```

```text
where     type            rules         conf  outcome
5:11      PERSON          en            0.90  kept
34:53     COMPANY_NAME    en            0.70  kept
59:69     IDENTIFIER      universal     0.50  displaced -- lost to PHONE (higher severity)
```

第二个问题才是关键，而在 `v0.12` 之前根本无法回答。
当什么都没命中时，`trace` 会跑另一个立场，
告诉你更宽的规则**本来会**抓到什么——只给形状，不给值；
如果两个立场都够不到，它会直说，并指向订正或模型层。

```bash
mamori audit --file inbox.txt   # 对你的文本来说哪些规则有用
mamori audit --dead             # 哪些规则从来没命中过
```

`audit` 第一次运行就发现：`v0.10` 加的三条凭据规则
**从来没有任何样本检验过**。
参见 [ADR 0027](docs/adr/0027-say-why-and-say-why-not.md)。

---

## 我的数据到底被怎么处理了

问它就好：

```bash
mamori privacy
```

答案是从**你的配置**算出来的，不是从这份 README 抄的：
哪些类型被阻断、哪些被替换，检测模型在哪里、信任边界是否允许它，
什么被保留、保留在哪里。任何扩大暴露面的设置都会作为警告输出，
并让退出码非零，方便在部署检查里直接失败。

下面是无论怎么配置都成立的主张，**每一条都带着「一旦不成立就会失败的测试」的名字**：

```text
  - Pattern detection contacts nothing. No socket is opened to protect a
    document with the default detectors.
    checked by test_promises.py::TestNothingLeavesTheMachine
```

这些测试是真的。`tests/test_promises.py` 把 `socket.connect` 换成会抛异常的函数，
然后跑完整条默认路径：所有语言包、评测框架、命令行。
将来如果某个依赖开始往外发请求，它会**在构建时失败**，而不是在你的部署里。
README 里的主张是规格，不是描述。
参见 [ADR 0019](docs/adr/0019-privacy-is-a-report-not-a-promise.md)、
[ADR 0020](docs/adr/0020-the-promises-are-checked-by-machine.md)。

最后一节写的是 mamori **无法替你确认**的事情，
比如你选的那家服务会不会留存你的提示词。
装作知道的报告，比闭嘴的报告更糟。

---

## 接入模型：同一台机器，或内网服务器

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
zh-core  (zh, 27 samples)
  leak rate             0.00%   (0/215 sensitive chars left uncovered)
  over-redaction        3.59%   (11/306 ordinary chars replaced)
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

### 模型层实际值多少

是实测，不是主张。本地跑 `llama3.1:8b`，balanced 立场，对内置数据集测量：

| | 泄漏率：仅规则 → +模型 | 过度打码 | precision |
|---|---|---|---|
| `en-core` | 2.01% → **0.67%** | 0.00% → 3.77% | 1.000 → 0.855 |
| `ja-core` | 0.71% → 0.71% | 0.00% → 5.41% | 1.000 → 0.868 |
| `zh-core` | 0.00% → 0.00% | 2.55% → 10.18% | 0.964 → 0.871 |

**在这个规模上，它是一个「提升英文召回」的工具。**
它补上了 `en-006`——没有任何前置标记的英文行文人名，正是这一层被设计出来要解决的情况——
但对日文和中文没有可测量的改善，同时在三种语言上都增加了过度打码。
本 README 早先声称它能覆盖中文人名，这一点没有得到支持：
中文规则在那套数据上的 recall 本来就是 1.000。

**在默认的 recall_first 立场下它是负收益：** wide 规则已经够到了那些值，
泄漏率不动，过度打码却从 1.44% 涨到 9.58%。在你用自己的数据测过之前，先关着。

自己测。值得看的只有差值：

```bash
mamori eval --compare --stance balanced -c mamori.json --cache answers.json
```

`--compare` 会点名列出发生变化的样本——聚合数字只会告诉你「有东西动了」，不会告诉你动了什么。
用**你自己的文档**来测量（这比这里的任何数字都更有说服力）的做法，见
[docs/measuring-your-own-data.md](docs/measuring-your-own-data.md)，
那里也写了要注意什么——那个文件装的就是你的真实数据。
`--cache` 用模型**和提示词**共同做键，所以重跑是免费的，
而改动一行指引只会让依赖旧措辞的那些答案失效。

这次测量把两个修正带回了代码。之前要求模型给出字符偏移量，结果 **52 个里对了 0 个**，
而这些值本身有 51 个确实在文档里。现在改为只报告值，位置由 mamori 自己定位
（[ADR 0022](docs/adr/0022-a-model-reports-values-not-offsets.md)）。
另外英文的误报全部是把 `OTHER_SENSITIVE` 当垃圾桶用；
只加了一条说明该类型用途的指引，过度打码就从 8.80% 减半到 4.43%。

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
`v0.6` 交付了代理，并把隐私主张变成可以查询、且由机器检查的东西。
`v0.7` 第一次测量了模型层，发现它一直在把模型答对的东西几乎全部丢掉，并修好了它。
`v0.8` 把最终决定权交给了运维人员。
`v0.9` 把评测数据扩到文档规模，发现了四个 44 字符样本无法暴露的检测缺陷。
`v0.10` 加了可以真正跑起来的 demo，并发现了测量框架自身的一个缺陷。
`v0.11` 加了替身值（默认关闭）。
`v0.12` 让它能说出「为什么」。
`v0.13` 针对中文和日文，而**失败的那两个修改比成功的两个教会了更多**。
`v0.14` 生成了一千份文档和一千条回复，一小时内找出五个缺陷。
`v0.15` 把这套语料用在中文上：**姓名后面跟着普通词语时，从第一个版本起就一直看不见**。
`v0.16` 让代理有了会话，并验证了一个搁置四个版本的论断——它是对的。
`v0.17` 把语料对准了「没有人打出来的提示词」，找出四个缺陷；其中三个与组装提示词无关，已经存在了好几个版本。
`v0.18` 发现**工具调用的参数从来就没有被保护过**。
`v0.19` 是面向部署的版本，它带来的检查器第一次运行就找出了本仓库自己的一个缺陷。
`v0.20` 用检测侧自 `v0.2` 以来的规模去测量还原侧，发现**流式与整体还原已经分歧了四个版本**。
`v0.21` 对替身值做了同样的事，把文档里最吓人的那一段变成了两个数字。
`v0.22` 第一次测量了**时间**，发现了一处平方复杂度——半兆字节的文档要跑十三秒。
`v0.23` 回答了 `v0.7` 留下的问题——比 8B 更大的模型**确实**会改变那张表；而一直测不出来的原因，是本库自己忽略了超时设置。
`v0.24` 在日语和中文上做了同样的测量，并用「测过之后说不」的方式，关掉了路线图上的最后一项。

| | |
|---|---|
| **v0.17** | 被组装出来的提示词。提示词越来越不是人打出来的，而是由检索层或智能体框架**渲染**出来的：头部有文件路径，结构里有哈希。它和其它一切一样，会有一份生成语料并被测量。而且结构部分作为**负例**来测——ID 被替换掉，就是一个带数字的缺陷。 |
| **v0.18** | 部署相关：宁可停下也不漏掉的 fail-closed 立场、扫描不该提交的值的 CI 检查、HTML 里的 `<PERSON_001>`，以及被拆到两个 JSON 键里的姓名。 |
| **v1.0** | 不是功能：稳定的 API、把承诺测试套件当作规格，以及配得上「实测」二字的数字。 |

这张表背后的理由——**计划了却没做的**、**采纳后发现多余的**，以及**刻意不做的**
——写在 [docs/proposals/0003](docs/proposals/0003-what-mamori-is-for.md)。

有两件事是想做的，但**刻意没有版本号**：可选安装的日语形态素分析适配器，以及
给无法只靠内存的部署用的加密存储。第三次给它们编号，只会变成一种不承认的方式
——不承认它们每次都输给了那一周语料里翻出来的东西。最老的未决问题仍然是：比 8B
更大的模型会不会改变模型层那张表。测量工具是有的，这里的硬件会超时。

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

---

## 许可证

Apache-2.0，见 [LICENSE](LICENSE)。

---
